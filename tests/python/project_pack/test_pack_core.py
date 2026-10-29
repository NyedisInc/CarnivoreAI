
from __future__ import annotations

import os
import subprocess

import pytest

from src.core.project_move.plan import PaneListing
from src.core.project_pack import archive_io, constants as K, inventory
from src.core.project_pack.trash import TrashError
from tests.python.project_pack.pack_world import (
    NO_PANES, conn_of, git, make_repo, pack_plan, project_row, run_pack_now, run_unpack_now, storage_row, tree_digest,
    unpack_plan)


def _failed(plan) -> set:
    return {c["id"] for c in plan.checks if not c["ok"]}


def test_round_trip_is_byte_exact_and_leaves_only_the_pack_files(world):
    before = tree_digest(world.root)
    plan = pack_plan(world)
    assert plan.ok, plan.failed()
    assert plan.sizes["file_count"] > 3 and plan.children[0]["name"] == "kid"
    run_pack_now(world, plan)
    row = storage_row(world)
    assert row["state"] == "packed", row
    assert sorted(os.listdir(world.root)) == sorted([row["archive_name"], K.MANIFEST_NAME, K.README_NAME])
    assert row["archive_bytes"] == os.stat(world.root / row["archive_name"]).st_size
    assert len(row["archive_sha256"]) == 64
    assert storage_row(world, "kid")["packed_in"] == world.ids["oldsite"]
    assert any(K.ORIGINALS_PREFIX in p.name for p in world.trash_dir.iterdir())
    unplan = unpack_plan(world)
    assert unplan.ok, unplan.failed()
    assert unplan.integrity["status"] == "ok"
    run_unpack_now(world, unplan)
    assert storage_row(world)["state"] == "unpacked" and storage_row(world, "kid")["state"] == "unpacked"
    assert tree_digest(world.root) == before
    assert len(list(world.trash_dir.iterdir())) == 4


@pytest.mark.parametrize("case", ["not_hidden", "live_session", "live_pane", "pane_unanswered", "modified_git",
                                  "stash", "ahead", "transcripts", "free_space", "pack_files_present", "live_child",
                                  "forbidden_home", "cloud_only"])
def test_each_refusal(world, monkeypatch, case):
    panes, expect = NO_PANES, {
        "not_hidden": "archived", "live_session": "no_live_sessions", "live_pane": "no_live_sessions",
        "pane_unanswered": "pane_listing", "modified_git": "git_clean", "stash": "git_clean", "ahead": "git_clean",
        "transcripts": "no_transcripts", "free_space": "free_space", "pack_files_present": "no_pack_files",
        "live_child": "children_archived", "forbidden_home": "not_forbidden", "cloud_only": "no_cloud_only"}[case]
    with conn_of(world) as conn:
        if case == "not_hidden":
            conn.execute("UPDATE projects SET archived_at = NULL WHERE id = ?", (world.ids["oldsite"],))
        if case == "live_child":
            conn.execute("UPDATE projects SET archived_at = NULL WHERE id = ?", (world.ids["kid"],))
        if case == "live_session":
            conn.execute("INSERT INTO sessions (session_uuid, working_dir, origin, lifecycle, tmux_name, tmux_created_epoch,"
                         " created_at, updated_at) VALUES ('s1', ?, 'created', 'running', 'live1', 1, 'n', 'n')",
                         (str(world.root / "src"),))
    if case == "live_pane":
        panes = PaneListing(True, (("x", 1, str(world.root)),))
    if case == "pane_unanswered":
        panes = PaneListing(False, reason="boom")
    if case == "modified_git":
        (world.root / "README").write_text("changed\n")
    if case == "stash":
        (world.root / "README").write_text("changed\n")
        git(world.root, "stash", "-q")
    if case == "ahead":
        (world.root / "n.txt").write_text("n")
        git(world.root, "add", "n.txt")
        git(world.root, "commit", "-q", "-m", "ahead")
    if case == "transcripts":
        (world.root / "-Users-x-proj").mkdir()
        (world.root / "-Users-x-proj" / "s.jsonl").write_text("{}")
    if case == "free_space":
        world.env.free_bytes = lambda path: 0
        world.env.margin = 1
    if case == "pack_files_present":
        (world.root / K.MANIFEST_NAME).write_text("x")
    if case == "forbidden_home":
        world.env.extra_forbidden = (str(world.root.parent),)
    if case == "cloud_only":
        monkeypatch.setattr(inventory, "SF_DATALESS", 0x8000)
        os.chflags(world.root / "src" / "a.py", 0x8000)
    plan = pack_plan(world, panes=panes)
    assert not plan.ok and expect in _failed(plan), plan.checks


def test_a_repo_with_no_remote_needs_the_flag_and_names_the_only_copy(world):
    make_repo(world.root / "src" / "scratch", None)
    refused = pack_plan(world)
    assert "git_local_only" in _failed(refused) and "src/scratch" in refused.local_only[0]
    accepted = pack_plan(world, accept_local_only=True)
    assert accepted.ok, accepted.failed()
    assert accepted.fingerprint != refused.fingerprint
    assert any("only copy" in c["message"] for c in accepted.checks if c["id"] == "git_local_only")


def test_a_file_edited_during_the_pack_fails_and_restores_everything(world, monkeypatch):
    before = tree_digest(world.root)
    real = archive_io.create_archive

    def edit_after_archiving(root, names, out, level=19, threads=0):
        real(root, names, out, level, threads)
        (world.root / "src" / "a.py").write_text("edited meanwhile\n")

    monkeypatch.setattr(archive_io, "create_archive", edit_after_archiving)
    run_pack_now(world)
    row = storage_row(world)
    assert row["state"] == "unpacked" and "changed while it was being packed" in row["last_error"]
    after = tree_digest(world.root)
    after["src/a.py"] = before["src/a.py"]
    assert {k: v for k, v in after.items() if k in before} == before
    assert sorted(os.listdir(world.root)) == sorted(p for p in before if "/" not in p)


def test_a_failed_trash_puts_the_originals_back(world):
    before = tree_digest(world.root)

    def broken(paths):
        raise TrashError("no trash today")

    world.env.trash = broken
    run_pack_now(world)
    row = storage_row(world)
    assert row["state"] == "unpacked" and "no trash today" in row["last_error"]
    assert tree_digest(world.root) == before


def test_a_modified_archive_warns_in_the_plan_and_the_unpack_refuses_it(world):
    run_pack_now(world)
    archive = world.root / storage_row(world)["archive_name"]
    with open(archive, "ab") as handle:
        handle.write(b"tamper")
    plan = unpack_plan(world)
    assert plan.integrity["status"] == "modified" and any("WARNING" in w for w in plan.warnings)
    assert plan.ok
    run_unpack_now(world, plan)
    row = storage_row(world)
    assert row["state"] == "packed" and "modified or replaced outside Carnivore" in row["last_error"]
    assert sorted(os.listdir(world.root)) == sorted([row["archive_name"], K.MANIFEST_NAME, K.README_NAME])


def test_same_size_tampering_is_caught_by_the_checksum_and_a_missing_archive_by_the_plan(world):
    run_pack_now(world)
    row = storage_row(world)
    archive = world.root / row["archive_name"]
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0xFF
    st = os.stat(archive)
    archive.write_bytes(bytes(data))
    os.utime(archive, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert unpack_plan(world).integrity["status"] == "ok"
    run_unpack_now(world)
    assert storage_row(world)["state"] == "packed" and "checksum" in storage_row(world)["last_error"]
    os.rename(archive, world.root / "moved-away")
    gone = unpack_plan(world)
    assert not gone.ok and gone.integrity["status"] == "missing"


def test_recovery_reverses_a_pack_a_restart_cut_off(world):
    from src.core.project_pack import recover, store

    (world.root / "x.tar.zst.partial").write_text("half")
    with conn_of(world) as conn:
        store.put(conn, world.ids["oldsite"], state="packing")
        assert recover.recover_all(conn, world.env) == {world.ids["oldsite"]: "unpacked"}
    assert not (world.root / "x.tar.zst.partial").exists() and (world.root / "src" / "a.py").is_file()
    assert storage_row(world)["state"] == "unpacked"


def test_the_archive_is_plain_tar_zst_a_stock_tool_reads(world):
    run_pack_now(world)
    archive = world.root / storage_row(world)["archive_name"]
    listing = subprocess.run([K.TAR_BIN, "-tf", str(archive)], capture_output=True, text=True, check=True).stdout
    assert "src/a.py" in listing and not any(line.startswith(("./", "oldsite/")) for line in listing.splitlines())
    assert project_row(world)["root"] == str(world.root)


from __future__ import annotations

import asyncio
import functools
import os
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any, List

import pytest

from test_session_move import EVENTS, hooks_for, seed, subject_of, world  # noqa: F401

from src.api import federation_pack_carry_routes as carry_routes  # noqa: E402
from src.api import federation_pack_move_routes as move_routes  # noqa: E402
from src.api import pack_migrate_env as env_mod  # noqa: E402
from src.core.pack.carry import scan, send  # noqa: E402
from src.core.pack.carry.step import CodeStep  # noqa: E402
from src.core.pack.migrate import apply  # noqa: E402
from src.core.pack.migrate.plan import MigrateError  # noqa: E402
from src.core.pack.move import session_move, turn  # noqa: E402

UUID = "sess-0001-aaaa"
BIN = bytes(range(256)) * 3


def git(path: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)
    return done.stdout.decode()


def make_world(world, tmp_path):
    a, b, link = world
    uid, root_a, root_b = seed(a, b, {})
    b.app.include_router(carry_routes.router, prefix="/api/v1")
    request = link(a, b)
    b.app.dependency_overrides[carry_routes._require_migrate] = b.app.dependency_overrides[move_routes._require_migrate]
    repo = root_a / "PillPanic"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / ".gitignore").write_text("*.log\n")
    for name in ("a.txt", "b.txt", "gone.txt"):
        (repo / name).write_text(f"{name} one\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "first")
    (repo / "a.txt").write_text("a staged change\n")
    git(repo, "add", "a.txt")
    (repo / "staged_new.txt").write_text("brand new, staged\n")
    git(repo, "add", "staged_new.txt")
    (repo / "b.txt").write_text("b unstaged change\n")
    (repo / "a.txt").write_text("a staged change\nand more unstaged\n")
    (repo / "gone.txt").unlink()
    (repo / "u.txt").write_text("untracked\n")
    (repo / "d").mkdir()
    (repo / "d" / "e.bin").write_bytes(BIN)
    (repo / "junk.log").write_text("ignored\n")
    (root_a / "note.txt").write_text("loose note\n")
    (root_a / "sub").mkdir()
    (root_a / "sub" / "pic.bin").write_bytes(BIN)
    return a, b, request, uid, root_a, root_b, tmp_path / "outbox"


def state(repo: Path) -> List[str]:
    return [git(repo, "rev-parse", "HEAD").strip(), git(repo, "status", "--porcelain"), git(repo, "diff", "--cached"), git(repo, "diff"),
            git(repo, "for-each-ref", "--format=%(refname)"), git(repo, "stash", "list")]


def send_all(request, uid: str, root_a: Path, outbox: Path, op_id: str = "op-test-1") -> List[Any]:
    found = scan.scan_project(str(root_a))
    assert [r.rel for r in found.repos] == ["PillPanic"] and found.files, found
    return asyncio.run(send.send_units(apply.guarded(request), found, project_uid=uid, op_id=op_id, outbox=str(outbox), air_gap=False, label="studio"))


def test_nested_repo_with_its_work_in_progress_and_loose_files_land_byte_equal(world, tmp_path) -> None:
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    before = state(root_a / "PillPanic")
    rows = send_all(request, uid, root_a, outbox)
    assert [r.get("restored", r.get("placed")) for r in rows] == [True, 2], rows
    src, dst = root_a / "PillPanic", root_b / "PillPanic"
    assert state(src) == before, "the source repo is exactly as it was (no stash, no ref, no index change)"
    assert git(dst, "rev-parse", "HEAD") == git(src, "rev-parse", "HEAD") and git(dst, "symbolic-ref", "--short", "HEAD").strip() == "main"
    assert git(dst, "status", "--porcelain") == git(src, "status", "--porcelain") and "M" in git(dst, "status", "--porcelain")
    assert git(dst, "diff", "--cached") == git(src, "diff", "--cached") and git(dst, "diff") == git(src, "diff")
    for name in ("a.txt", "b.txt", "staged_new.txt", "u.txt", "d/e.bin"):
        assert (dst / name).read_bytes() == (src / name).read_bytes(), name
    assert not (dst / "gone.txt").exists() and not (dst / "junk.log").exists()
    assert "refs/carnivore-wip" not in git(dst, "for-each-ref") + git(src, "for-each-ref")
    assert (root_b / "note.txt").read_bytes() == b"loose note\n" and (root_b / "sub" / "pic.bin").read_bytes() == BIN
    assert not list(root_b.glob(".carnivore-carry-*")) and not list(outbox.glob("*")) and not list((b.state / "pack" / "inbox").glob("*.blob"))
    again = send_all(request, uid, root_a, outbox, op_id="op-test-2")
    assert [r.get("restored", r.get("placed")) for r in again] == [True, 0] and state(dst)[1:4] == state(src)[1:4]


def test_a_path_outside_the_project_is_refused(world, tmp_path) -> None:
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root_b / "escape").symlink_to(outside)
    for rel in ("../x", "/etc", "a/../../x", "PillPanic/.git", ".GIT/hooks", "escape/PillPanic"):
        unit = {"kind": "repo", "rel": rel, "branch": "main", "head": "a" * 40, "commits": True, "blob_id": "b-0123456789abcdef"}
        with pytest.raises(MigrateError) as refused:
            asyncio.run(send.call(apply.guarded(request), send.APPLY_PATH, {"op_id": "op-bad", "project_uid": uid, "unit": unit}, "code"))
        assert refused.value.code == "unsafe_path", (rel, refused.value.code)
    assert list(outside.iterdir()) == [] and not (root_b / "PillPanic").exists()
    with closing(b.conn()) as conn:
        conn.execute("UPDATE projects SET home_install_id = 'iid-stranger' WHERE uid = ?", (uid,))
        conn.commit()
    with pytest.raises(MigrateError) as stranger:
        asyncio.run(send.call(apply.guarded(request), send.CHECK_PATH, {"project_uid": uid, "units": [], "which": ["git"]}, "check"))
    assert stranger.value.code == "not_a_counterpart"


def test_a_target_with_its_own_changes_refuses_and_nothing_is_written(world, tmp_path) -> None:
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    send_all(request, uid, root_a, outbox)
    (root_b / "note.txt").write_text("the target's own edit\n")
    (root_a / "newer.txt").write_text("sent, but must not land\n")
    with pytest.raises(MigrateError) as refused:
        send_all(request, uid, root_a, outbox, op_id="op-test-3")
    assert refused.value.code == "target_has_own_changes" and "note.txt" in refused.value.detail, refused.value
    assert (root_b / "note.txt").read_text() == "the target's own edit\n" and not (root_b / "newer.txt").exists()
    (root_a / "newer.txt").unlink()
    dst = root_b / "PillPanic"
    (dst / "b.txt").write_text("the target's own repo edit\n")
    git(dst, "add", "b.txt")
    git(dst, "commit", "-q", "-m", "target's own commit")
    mine = state(dst)
    with pytest.raises(MigrateError) as diverged:
        send_all(request, uid, root_a, outbox, op_id="op-test-4")
    assert diverged.value.code == "target_has_own_changes" and state(dst) == mine


def test_the_code_step_carries_the_units_before_the_sleep_for_a_target_with_the_capability(world, tmp_path, monkeypatch) -> None:
    a, b, request, uid, root_a, root_b, outbox = make_world(world, tmp_path)
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))

    async def commits() -> Any:
        return {"machine": "studio", "sent": True}

    step = CodeStep(root=str(root_a), air_gap=False, label="studio", target_caps=[scan.CARRY_TREE], carry_commits=commits,
                    request=apply.guarded(request), project_uid=uid, outbox=str(outbox))
    EVENTS.clear()
    asyncio.run(session_move.move_session(env_mod.source_env(), hooks_for(a, ["idle"], {UUID: "larkspur"}), apply.guarded(request), subject=subject_of(a, UUID),
                                          target_install_id="iid-b", target_label="studio", wait_seconds=5, code=step))
    assert git(root_b / "PillPanic", "status", "--porcelain") == git(root_a / "PillPanic", "status", "--porcelain")
    assert (root_b / "note.txt").exists() and b.launched, "the agent woke on b after the work arrived"

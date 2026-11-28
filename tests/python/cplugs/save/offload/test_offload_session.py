
from __future__ import annotations

import hashlib
import os
import stat
import time
from pathlib import Path
from typing import Dict

import pytest
from fastapi import HTTPException

from src.core.backup_health import offloaded_marker
from src.core.blobcodec import place
from src.plugins.save.offload import constants as C
from src.plugins.save.offload import icloud, ledger as ledger_mod, offload_routes, reconcile, restore_chain, restore_routes
from src.plugins.save.engine import layout
from src.plugins.save.offload.ledger import Entry, Ledger, LedgerUnreadable
from src.plugins.save.vault import points as vault_points, retention
from src.plugins.save.vault.chunks import decompress
from src.plugins.sdk import session_chains as sdk
from src.plugins.sdk.session_chains import ChainSnapshot, RunningScan, SessionFacts
from tests.python.cplugs.save.vault_helpers import World, jsonl

ID = {n: f"00000000-0000-4000-8000-{i:012x}" for i, n in enumerate(["c1", "c2", "c3"], 1)}


def digest_tree(world: World) -> Dict[str, tuple]:
    out = {}
    for path in sorted(p for p in world.home.rglob("*") if p.is_file()):
        info = path.stat()
        out[str(path.relative_to(world.home))] = (hashlib.sha256(path.read_bytes()).hexdigest(), stat.S_IMODE(info.st_mode), info.st_mtime_ns)
    return out


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = World(tmp_path)
    os.chmod(world.state, 0o700)
    for n in ("c1", "c2", "c3"):
        world.write_conversation(jsonl(5, seed=int(n[1])), conv=ID[n], subagents=1, tool_results=1)
    old = time.time() - 3 * 86400
    for path in [p for p in world.home.rglob("*") if p.is_file()]:
        os.utime(path, (old, old))
    os.chmod(world.transcript(ID["c1"]), 0o640)
    for n in ("c1", "c2", "c3"):
        world.capture(ID[n])
    snapshot = ChainSnapshot((SessionFacts("S1", "t", 1, "local", "stopped", "closed_by_user", False, False, ID["c3"], old),),
                             {ID["c3"]: frozenset({ID["c2"]}), ID["c2"]: frozenset({ID["c1"]})})
    monkeypatch.setattr(sdk, "read_snapshot", lambda: snapshot)
    monkeypatch.setattr(sdk, "read_running", lambda: RunningScan(frozenset(), 0))
    monkeypatch.setattr(offload_routes.RUNTIME, "vault", lambda: world.vault)
    monkeypatch.setattr(offload_routes.RUNTIME, "sources", lambda: world.sources)
    monkeypatch.setattr(restore_routes.RUNTIME, "vault", lambda: world.vault)
    monkeypatch.setattr(restore_routes.RUNTIME, "sources", lambda: world.sources)
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    return world


def ledger_of(world: World) -> Ledger:
    return Ledger(world.vault.root, world.state)


def refusal(world: World) -> dict:
    with pytest.raises(HTTPException) as caught:
        offload_routes._run("S1", False)
    assert caught.value.status_code == 409
    return caught.value.detail


def test_offload_is_refused_while_the_install_is_not_ready_and_moves_nothing(installed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    before = digest_tree(installed)
    monkeypatch.setattr(icloud, "icloud_root", lambda: installed.home)
    body = refusal(installed)
    assert body["code"] == C.CODE_NOT_READY and C.BLOCKER_ICLOUD_PATH in body["reasons"]
    assert digest_tree(installed) == before and not ledger_of(installed).path.exists() and not (installed.state / C.HOLDING_DIRNAME).exists()


def test_offload_is_refused_when_a_file_does_not_match_the_vault_and_moves_nothing(installed: World) -> None:
    side = next(installed.transcript(ID["c3"]).parent.rglob("agent-0.jsonl"))
    raw = side.read_bytes()
    side.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    old = time.time() - 3 * 86400
    os.utime(side, (old, old))
    before = digest_tree(installed)
    body = refusal(installed)
    assert body["code"] == C.CODE_VERIFY_FAILED and "agent-0.jsonl" in body["detail"]
    assert digest_tree(installed) == before and not ledger_of(installed).path.exists(), "every conversation is verified before any moves"


def test_a_dry_run_reports_and_changes_nothing(installed: World) -> None:
    before = digest_tree(installed)
    out = offload_routes._run("S1", True)
    assert out.dry_run and {c.status for c in out.conversations} == {"would_offload"} and len(out.conversations) == 3
    assert digest_tree(installed) == before and not ledger_of(installed).path.exists()


def test_offload_then_restore_round_trips_byte_exact_and_clears_the_ledger(installed: World) -> None:
    before = digest_tree(installed)
    out = offload_routes._run("S1", False)
    assert {c.status for c in out.conversations} == {"offloaded"} and out.bytes > 0
    assert not [p for p in installed.home.rglob("*") if p.is_file()]
    held = sorted(p for p in (installed.state / C.HOLDING_DIRNAME).rglob("*") if p.is_file())
    assert len(held) == len(before)
    entries = ledger_of(installed).read()
    assert {e.state for e in entries.values()} == {C.STATE_OFFLOADED} and set(entries) == set(ID.values())
    assert all(e.group == ["S1"] and e.purge_after > e.offloaded_at for e in entries.values())
    assert set(offloaded_marker.read(installed.state).rows) == set(ID.values())
    holding = installed.state / C.HOLDING_DIRNAME
    inodes = {Path(*p.relative_to(holding).parts[2:]): p.stat().st_ino for p in held}
    back = restore_routes.run_restore("S1", None, False)
    assert {c.status for c in back.conversations} == {"written"}
    assert digest_tree(installed) == before
    restored = {p.relative_to(installed.home): p.stat().st_ino for p in installed.projects.rglob("*") if p.is_file()}
    assert restored and all(inodes[rel] == ino for rel, ino in restored.items()), "the held files came back by link, not a rewrite from the vault"
    assert ledger_of(installed).read() == {} and offloaded_marker.read(installed.state).rows == {}
    assert not any(p.is_file() for p in (installed.state / C.HOLDING_DIRNAME).rglob("*")) and not (installed.state / C.HOLDING_DIRNAME / ID["c1"]).exists()


def test_restore_after_the_holding_folder_is_gone_comes_from_the_vault(installed: World) -> None:
    before = digest_tree(installed)
    offload_routes._run("S1", False)
    for held in [p for p in (installed.state / C.HOLDING_DIRNAME).rglob("*") if p.is_file()]:
        held.unlink()
    back = restore_routes.run_restore("S1", None, False)
    assert {c.status for c in back.conversations} == {"written"} and digest_tree(installed) == before and ledger_of(installed).read() == {}


def test_a_failed_move_puts_every_file_of_the_chain_back(installed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    before = digest_tree(installed)
    real = os.rename
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 9:
            raise OSError(28, "No space left on device")
        return real(src, dst)

    monkeypatch.setattr("src.plugins.save.offload.move.os.rename", flaky)
    body = refusal(installed)
    assert body["code"] == C.CODE_MOVE_FAILED and body["stuck"] == []
    assert ledger_of(installed).read() == {} and offloaded_marker.read(installed.state).rows == {}
    assert digest_tree(installed) == before


def test_the_mass_gone_alarm_does_not_count_offloaded_units_but_still_counts_a_real_wipe(tmp_path: Path) -> None:
    world = World(tmp_path)
    ids = [f"00000000-0000-4000-8000-{i:012x}" for i in range(100, 122)]
    for conv in ids:
        world.write_conversation(jsonl(3, seed=1), conv=conv, enc=f"-p{conv[-3:]}", subagents=0, tool_results=0)
        world.capture(conv)
    now = time.time()
    assert retention.assess(world.vault, now=now)["mass_gone"] is None
    ledger = Ledger(world.vault.root, world.state)
    for conv in ids[:12]:
        ledger.put(Entry(conv, conv, "claude", None, "p", "m", 1, 1, ["S"], C.STATE_OFFLOADED, now))
    for conv in ids:
        for path in world.transcript(conv, enc=f"-p{conv[-3:]}").parent.rglob("*"):
            if path.is_file():
                path.unlink()
    report = retention.assess(world.vault, now=now + 5)["mass_gone"]
    assert report is not None and report["count"] == 10, "only the 10 that left without a ledger entry count"


def test_the_ledger_survives_a_restart_and_an_unreadable_one_is_never_read_as_empty(installed: World) -> None:
    offload_routes._run("S1", False)
    assert set(Ledger(installed.vault.root, installed.state).read()) == set(ID.values())
    assert ledger_mod.intentional_units(installed.vault.root) == frozenset(ID.values())
    ledger_of(installed).path.write_text("{not json")
    with pytest.raises(ledger_mod.LedgerUnreadable):
        ledger_of(installed).read()
    assert ledger_mod.intentional_units(installed.vault.root) == frozenset()


def test_the_vault_point_an_offload_depends_on_cannot_be_deleted(installed: World) -> None:
    offload_routes._run("S1", False)
    point = installed.vault.manifests.newest(ID["c1"]).point_id  # type: ignore[union-attr]
    with pytest.raises(vault_points.OffloadedError):
        vault_points.delete_point(installed.vault, ID["c1"], point)
    assert ledger_mod.protects(installed.vault.root, ID["c1"], point) and not ledger_mod.protects(installed.vault.root, ID["c1"], "other")


def test_a_cut_off_offload_is_settled_at_the_next_start(installed: World) -> None:
    before = digest_tree(installed)
    offload_routes._run("S1", False)
    led = ledger_of(installed)
    homes = {"claude": installed.home, "claude/projects": installed.projects}
    for conv in ID.values():
        led.update(conv, state=C.STATE_OFFLOADING)
    out = reconcile.reconcile(installed.vault, led, homes)
    assert set(out.values()) == {reconcile.OUTCOME_OFFLOADED} and {e.state for e in led.read().values()} == {C.STATE_OFFLOADED}
    destination = restore_chain.restore.homes_destination(homes)
    main = installed.vault.manifests.newest(ID["c2"]).main()  # type: ignore[union-attr]
    held = installed.state / C.HOLDING_DIRNAME / ID["c2"] / main.home / main.rel
    os.rename(held, destination(main))
    led.update(ID["c2"], state=C.STATE_OFFLOADING)
    out = reconcile.reconcile(installed.vault, led, homes)
    assert out == {ID["c2"]: reconcile.OUTCOME_DROPPED} and set(led.read()) == {ID["c1"], ID["c3"]}
    assert not any(p.is_file() for p in (installed.state / C.HOLDING_DIRNAME / ID["c2"]).rglob("*")), "the rest of c2 went back too"
    assert {k: v for k, v in digest_tree(installed).items() if ID["c2"] in k} == {k: v for k, v in before.items() if ID["c2"] in k}


def test_the_strict_placer_refuses_where_the_default_placer_renames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_links(*_a, **_k):
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(place.os, "link", no_links)
    temp, dest = tmp_path / "t.partial", tmp_path / "d.jsonl"
    temp.write_bytes(b"x\n")
    with pytest.raises(place.PlaceUnsupported):
        place.place_no_clobber(temp, dest, strict=True)
    assert not dest.exists() and temp.exists()
    place.place_no_clobber(temp, dest)
    assert dest.read_bytes() == b"x\n" and not temp.exists()
    temp.write_bytes(b"y\n")
    dest.write_bytes(b"mine\n")
    with pytest.raises(place.PlaceConflict):
        place.place_no_clobber(temp, dest, strict=True)
    assert dest.read_bytes() == b"mine\n"


def test_the_offload_restore_passes_strict_so_a_volume_without_links_fails_instead_of_renaming(installed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    offload_routes._run("S1", False)
    for held in [p for p in (installed.state / C.HOLDING_DIRNAME).rglob("*") if p.is_file()]:
        held.unlink()
    monkeypatch.setattr(place.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError(1, "Operation not permitted")))
    out = restore_chain.restore_conversation(installed.vault, ID["c1"], {"claude": installed.home, "claude/projects": installed.projects}, ledger=ledger_of(installed))
    assert out.status == "failed" and "hard link" in out.detail and not installed.transcript(ID["c1"]).exists()
    assert ledger_of(installed).read()[ID["c1"]].state == C.STATE_FAILED


def test_the_icloud_check_reads_the_real_path_not_an_attribute(tmp_path: Path) -> None:
    drive = tmp_path / "Library" / "Mobile Documents"
    (drive / "com~apple~CloudDocs").mkdir(parents=True)
    outside = tmp_path / "Application Support" / "projects"
    outside.mkdir(parents=True)
    inside = drive / "com~apple~CloudDocs" / "projects"
    inside.mkdir()
    link_out, link_in = tmp_path / "out-link", tmp_path / "in-link"
    link_out.symlink_to(outside)
    link_in.symlink_to(inside)
    assert icloud.blockers([link_out, outside], drive) == []
    assert icloud.blockers([link_in], drive) == [C.BLOCKER_ICLOUD_PATH]
    assert icloud.blockers([tmp_path / "Library" / "Mobile Documents-x" / "p"], drive) == []
    assert icloud.blockers([drive / "new-holding"], drive) == [C.BLOCKER_ICLOUD_PATH]


def assert_untouched(world: World, before: Dict[str, tuple]) -> None:
    assert digest_tree(world) == before
    assert not [p for p in (world.state / C.HOLDING_DIRNAME).rglob("*") if p.is_file()]
    assert not ledger_of(world).read()


def test_a_file_written_after_its_verification_is_never_moved(installed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.plugins.save.offload import run

    real = run.verify_conversation
    target = installed.transcript(ID["c2"])

    def verify_then_append(blobs, plan, point):
        proof = real(blobs, plan, point)
        if plan.unit == ID["c2"]:
            with open(target, "ab") as handle:
                handle.write(b'{"late": true}\n')
        return proof

    monkeypatch.setattr(run, "verify_conversation", verify_then_append)
    body = refusal(installed)
    assert body["code"] == C.CODE_IN_USE
    assert target.read_bytes().endswith(b'{"late": true}\n')
    assert_untouched(installed, digest_tree(installed))


@pytest.mark.parametrize("busy_from_call", [3, 4], ids=["right_before_the_move", "right_after_the_move"])
def test_a_claude_that_opens_the_conversation_during_the_offload_stops_it(installed: World, monkeypatch: pytest.MonkeyPatch, busy_from_call: int) -> None:
    calls = {"n": 0}

    def running() -> RunningScan:
        calls["n"] += 1
        return RunningScan(frozenset({ID["c1"]}) if calls["n"] >= busy_from_call else frozenset(), 0)

    monkeypatch.setattr(sdk, "read_running", running)
    before = digest_tree(installed)
    body = refusal(installed)
    assert body["code"] == C.CODE_IN_USE and calls["n"] >= busy_from_call
    assert_untouched(installed, before)


def test_a_marker_that_cannot_be_written_stops_the_offload_before_any_file_moves(installed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger_mod.offloaded_marker, "write", lambda *_a, **_k: False)
    before = digest_tree(installed)
    body = refusal(installed)
    assert body["code"] == C.CODE_LEDGER_UNREADABLE
    assert_untouched(installed, before)


def test_the_marker_never_forgets_an_offload_its_ledger_cannot_see(installed: World, tmp_path: Path) -> None:
    offload_routes._run("S1", False)
    (tmp_path / "another-vault").mkdir()
    other = Ledger(tmp_path / "another-vault", installed.state)
    other.sync_marker()
    assert set(offloaded_marker.read(installed.state).rows) == set(ID.values())
    extra = "00000000-0000-4000-8000-0000000000ff"
    row = Entry(conversation_id=extra, unit=extra, family="claude", encoded_folder=None, point_id="p", manifest_sha256="0" * 64, files=1, bytes=1, group=["S2"])
    with pytest.raises(LedgerUnreadable):
        other.put(row)
    assert set(offloaded_marker.read(installed.state).rows) == set(ID.values())
    layout.atomic_write_json(other.path, {"version": 1, "conversations": {}})
    other.put(row)
    assert set(offloaded_marker.read(installed.state).rows) == set(ID.values()) | {extra}, "a write through one ledger must not drop another's rows"
    other.remove(extra)
    assert set(offloaded_marker.read(installed.state).rows) == set(ID.values()), "a removal drops exactly that row"


def test_an_offload_is_refused_when_a_restore_would_put_the_files_somewhere_else(installed: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.plugins.save.vault.units import Sources

    first = tmp_path / "profile-two" / "projects"
    first.mkdir(parents=True)
    two_roots = Sources((first, installed.projects), installed.codex, installed.state)
    monkeypatch.setattr(offload_routes.RUNTIME, "sources", lambda: two_roots)
    before = digest_tree(installed)
    body = refusal(installed)
    assert body["code"] == C.CODE_VERIFY_FAILED and "restore" in body["detail"]
    assert_untouched(installed, before)


def test_a_marker_row_no_ledger_holds_is_dropped_at_start_only_when_its_conversation_is_on_disk(installed: World) -> None:
    gone = "00000000-0000-4000-8000-0000000000fe"
    assert offloaded_marker.write(installed.state, [(ID["c1"], ["S1"], 10), (gone, ["S9"], 10)])
    ledger_of(installed).sync_marker(on_disk=lambda cid: cid in ID.values())
    assert set(offloaded_marker.read(installed.state).rows) == {gone}


def test_a_purged_session_is_rebuilt_from_the_vaults_chunk_files_alone(installed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    before = digest_tree(installed)
    offload_routes._run("S1", False)
    holding = installed.state / C.HOLDING_DIRNAME
    for path in sorted(holding.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    holding.rmdir()
    assert all(not installed.transcript(ID[n]).exists() for n in ID), "the offload must have taken the transcripts off disk"
    store = installed.vault.blobs
    real_get, real_write = type(store).get, restore_chain.restore.write_entry
    chunk_files: Dict[str, tuple] = {}
    written: list = []

    def get_from_disk(self, ref):  # type: ignore[no-untyped-def]
        found = self.find(ref.sha256)
        assert found is not None and found[0].is_file() and Path(installed.vault.root) in found[0].parents
        chunk_files[ref.sha256] = found
        return real_get(self, ref)

    def write_spy(blobs, entry, dest, **kw):  # type: ignore[no-untyped-def]
        written.append(dest)
        return real_write(blobs, entry, dest, **kw)

    monkeypatch.setattr(type(store), "get", get_from_disk)
    monkeypatch.setattr(restore_chain.restore, "write_entry", write_spy)
    back = restore_routes.run_restore("S1", None, False)
    assert {c.status for c in back.conversations} == {"written"} and back.started_session is False
    assert len(written) == sum(c.written for c in back.conversations) > 0, "every file came from the vault, none from a held copy"
    assert chunk_files and all(hashlib.sha256(decompress(path.read_bytes(), codec)).hexdigest() == sha for sha, (path, codec) in chunk_files.items())
    assert digest_tree(installed) == before and ledger_of(installed).read() == {}


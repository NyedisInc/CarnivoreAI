
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from src.plugins.save.offload import offload_routes, reconcile, restore_routes, target_folder
from src.plugins.save.offload import constants as C
from src.plugins.sdk import session_chains as sdk
from src.plugins.sdk import transcript_files as tf
from src.plugins.sdk.session_chains import ChainSnapshot, RunningScan, SessionFacts
from tests.python.cplugs.save.offload.fleet import conv_id, ledger_of
from tests.python.cplugs.save.vault_helpers import World, jsonl

CONV = conv_id(1)
WORKING_DIR = "/Users/x/Development/Org/Tooling/home-assistant"
SHORT = "-Users-x-Development-Org-Tooling-home-assistant"
LONG = "-Users-x-Library-Mobile-Documents-com-apple-CloudDocs-Sync-Development-Org-Tooling-home-assistant"


def wire(world: World, monkeypatch: pytest.MonkeyPatch, working_dir: str | None) -> None:
    facts = SessionFacts("S1", "t", 1, "local", "stopped", "closed_by_user", False, False, CONV, time.time() - 3 * 86400, working_dir)
    monkeypatch.setattr(sdk, "read_snapshot", lambda: ChainSnapshot((facts,), {}))
    monkeypatch.setattr(sdk, "read_running", lambda: RunningScan(frozenset(), 0))
    for module in (offload_routes, restore_routes):
        monkeypatch.setattr(module.RUNTIME, "vault", lambda: world.vault)
        monkeypatch.setattr(module.RUNTIME, "sources", lambda: world.sources)
    monkeypatch.setenv("HOME", str(world.state.parent / "fakehome"))
    monkeypatch.setattr(tf, "state_dir", lambda: world.state)


@pytest.fixture
def long_spelling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    world = World(tmp_path)
    os.chmod(world.state, 0o700)
    world.write_conversation(jsonl(5, seed=1), conv=CONV, enc=LONG, subagents=1, tool_results=1)
    old = time.time() - 3 * 86400
    for path in [p for p in world.home.rglob("*") if p.is_file()]:
        os.utime(path, (old, old))
    world.capture(CONV)
    world.bytes = {str(p.relative_to(world.projects / LONG)): p.read_bytes() for p in (world.projects / LONG).rglob("*") if p.is_file()}  # type: ignore[attr-defined]
    wire(world, monkeypatch, WORKING_DIR)
    return world


def files_under(world: World, folder: str) -> dict:
    root = world.projects / folder
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()} if root.exists() else {}


def test_an_offloaded_conversation_comes_back_where_its_resume_looks(long_spelling: World) -> None:
    assert {c.status for c in offload_routes._run("S1", False).conversations} == {"offloaded"}
    out = restore_routes.run_restore("S1", None, False)
    assert [c.status for c in out.conversations] == ["written"]
    assert files_under(long_spelling, SHORT) == long_spelling.bytes  # type: ignore[attr-defined]
    assert (long_spelling.projects / SHORT / CONV / "subagents" / "agent-0.jsonl").is_file()
    assert files_under(long_spelling, LONG) == {}
    assert any(n.startswith("restored_into: ") and n.endswith(SHORT) for n in out.conversations[0].notes)
    assert ledger_of(long_spelling).read() == {} and (long_spelling.home / "file-history" / CONV / "abc@v1").is_file()


def test_a_plain_restore_also_goes_to_the_resume_folder(long_spelling: World) -> None:
    shutil.rmtree(long_spelling.projects / LONG)
    out = restore_routes.run_restore(None, CONV, False)
    assert [c.status for c in out.conversations] == ["written"]
    assert files_under(long_spelling, SHORT) == long_spelling.bytes  # type: ignore[attr-defined]


def test_a_different_file_at_the_resume_folder_is_refused_and_nothing_is_written(long_spelling: World) -> None:
    offload_routes._run("S1", False)
    other = long_spelling.projects / SHORT / f"{CONV}.jsonl"
    other.parent.mkdir(parents=True)
    other.write_bytes(b'{"other":"conversation"}\n')
    out = restore_routes.run_restore("S1", None, False)
    assert [c.status for c in out.conversations] == ["conflict"] and out.conversations[0].conflicts == [str(other)]
    assert other.read_bytes() == b'{"other":"conversation"}\n' and files_under(long_spelling, SHORT) == {f"{CONV}.jsonl": other.read_bytes()}
    entry = ledger_of(long_spelling).get(CONV)
    assert entry is not None and (entry.state, entry.error_code, entry.error_path) == (C.STATE_CONFLICT, "conflict", str(other))
    assert any((long_spelling.state / C.HOLDING_DIRNAME / CONV).rglob("*.jsonl"))


def test_no_session_folder_keeps_the_recorded_folder(long_spelling: World, monkeypatch: pytest.MonkeyPatch) -> None:
    wire(long_spelling, monkeypatch, None)
    shutil.rmtree(long_spelling.projects / LONG)
    out = restore_routes.run_restore(None, CONV, False)
    assert [c.status for c in out.conversations] == ["written"] and out.conversations[0].notes == []
    assert files_under(long_spelling, LONG) == long_spelling.bytes and files_under(long_spelling, SHORT) == {}  # type: ignore[attr-defined]


def test_the_settle_pass_judges_a_cut_off_restore_at_the_resume_folder(long_spelling: World) -> None:
    offload_routes._run("S1", False)
    restore_routes.run_restore("S1", None, False)
    point = long_spelling.vault.manifests.newest(CONV)
    from src.plugins.save.offload.ledger import Entry  # noqa: PLC0415

    ledger_of(long_spelling).put(Entry(CONV, CONV, "claude", LONG, point.point_id, "0" * 64, len(point.files), 0, state=C.STATE_RESTORING))  # type: ignore[union-attr]
    folders = target_folder.resume_folders(sdk.read_snapshot(), [CONV])
    assert folders == {CONV: SHORT}
    homes = offload_routes.claude_homes(long_spelling.sources.claude_roots)
    assert reconcile.reconcile(long_spelling.vault, ledger_of(long_spelling), homes, folders) == {CONV: reconcile.OUTCOME_DROPPED}


def test_the_resume_folder_prefers_the_current_holder_and_skips_other_computers() -> None:
    old = SessionFacts("A", None, None, "local", "stopped", None, False, False, "c1", 10.0, "/Users/x/a")
    newer_chain = SessionFacts("B", None, None, "local", "stopped", None, False, False, "c2", 99.0, "/Users/x/b")
    remote = SessionFacts("R", None, None, "peer-1", "stopped", None, False, False, "c1", 999.0, "/Users/demo/r")
    snap = ChainSnapshot((old, newer_chain, remote), {"c2": frozenset({"c1"})})
    assert target_folder.resume_folders(snap, ["c1", "c2", "c9"]) == {"c1": "-Users-x-a", "c2": "-Users-x-b"}




def grow_at_long(world: World) -> tuple:
    main = world.projects / LONG / f"{CONV}.jsonl"
    with open(main, "ab") as handle:
        handle.write(b'{"type":"user","message":"one more turn"}\n')
    return main, files_under(world, LONG)


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_plain_restore_writes_nothing_when_the_conversation_is_newer_at_its_recorded_folder(long_spelling: World, dry_run: bool) -> None:
    main, before = grow_at_long(long_spelling)
    out = restore_routes.run_restore(None, CONV, dry_run)
    [one] = out.conversations
    assert (one.status, one.written) == ("present_elsewhere", 0)
    assert f"present_elsewhere: {main} (disk_newer)" in one.notes
    assert files_under(long_spelling, SHORT) == {} and files_under(long_spelling, LONG) == before


def test_a_copy_under_a_third_spelling_is_found_by_the_scan(long_spelling: World) -> None:
    third = long_spelling.projects / "-Users-x-some-other-spelling-home-assistant"
    shutil.move(str(long_spelling.projects / LONG), str(third))
    out = restore_routes.run_restore(None, CONV, False)
    assert [c.status for c in out.conversations] == ["present_elsewhere"]
    assert f"present_elsewhere: {third / (CONV + '.jsonl')} (already_present)" in out.conversations[0].notes
    assert files_under(long_spelling, SHORT) == {}


def test_a_point_holding_both_spellings_is_not_remapped(long_spelling: World) -> None:
    from dataclasses import replace  # noqa: PLC0415

    from src.plugins.save.offload import homes as homes_mod  # noqa: PLC0415

    point = long_spelling.vault.manifests.newest(CONV)
    main = point.main()  # type: ignore[union-attr]
    twin = replace(main, rel=main.rel.replace(LONG, SHORT))  # type: ignore[union-attr]
    both = replace(point, files=[*point.files, twin])  # type: ignore[union-attr]
    homes = offload_routes.claude_homes(long_spelling.sources.claude_roots)
    destination = homes_mod.point_destination(homes, both, SHORT)
    paths = [destination(f) for f in both.files]
    assert len(set(paths)) == len(paths)
    assert destination(main) == long_spelling.projects / LONG / f"{CONV}.jsonl"  # type: ignore[arg-type]


def test_the_conversation_route_answers_503_when_the_sessions_cannot_be_read(long_spelling: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException  # noqa: PLC0415

    def unreadable() -> ChainSnapshot:
        raise sdk.SessionChainsUnreadable("database is locked")

    monkeypatch.setattr(sdk, "read_snapshot", unreadable)
    shutil.rmtree(long_spelling.projects / LONG)
    with pytest.raises(HTTPException) as caught:
        restore_routes.run_restore(None, CONV, False)
    assert caught.value.status_code == 503 and caught.value.detail["code"] == "sessions_unreadable"  # type: ignore[index]
    assert files_under(long_spelling, SHORT) == {} and files_under(long_spelling, LONG) == {}


@pytest.mark.parametrize(("working_dir", "expected"), [
    ("/Users/x/Development/proj/", {"c1": "-Users-x-Development-proj"}),
    ("/Users/x/Development/./proj//", {"c1": "-Users-x-Development-proj"}),
    ("Development/proj", {}),
    ("~/Development/proj", {}),
])
def test_the_resume_folder_is_slugged_from_a_normalized_absolute_path(working_dir: str, expected: dict) -> None:
    row = SessionFacts("A", None, None, "local", "stopped", None, False, False, "c1", 10.0, working_dir)
    assert target_folder.resume_folders(ChainSnapshot((row,), {}), ["c1"]) == expected


from __future__ import annotations

import ast
import hashlib
import inspect
import os
import shutil
import stat
from dataclasses import replace
from pathlib import Path
from typing import Dict, List

import pytest
from fastapi import HTTPException

from src.plugins.save import routes as save_routes, start
from src.plugins.save.offload import restore_chain, restore_routes
from src.plugins.save.vault import constants as K
from src.plugins.sdk.session_chains import ChainSnapshot, SessionFacts
from tests.python.cplugs.save.vault_helpers import World, jsonl

ID = {n: f"00000000-0000-4000-8000-{i:012x}" for i, n in enumerate(["c1", "c2", "c3", "x1"], 1)}
OFFLOAD_DIR = Path(restore_chain.__file__).parent


def digest_tree(world: World) -> Dict[str, tuple]:
    out = {}
    for path in sorted(p for p in world.home.rglob("*") if p.is_file()):
        info = path.stat()
        out[str(path.relative_to(world.home))] = (hashlib.sha256(path.read_bytes()).hexdigest(), stat.S_IMODE(info.st_mode), info.st_mtime_ns)
    return out


def homes(world: World) -> Dict[str, Path]:
    return {"claude": world.home, "claude/projects": world.projects}


@pytest.fixture
def world(tmp_path: Path) -> World:
    w = World(tmp_path)
    for n in ("c1", "c2", "c3"):
        w.write_conversation(jsonl(6, seed=len(n) + int(n[1])), conv=ID[n], subagents=1, tool_results=1)
    os.chmod(w.transcript(ID["c1"]), 0o640)
    for n in ("c1", "c2", "c3"):
        w.capture(ID[n])
    w.before = digest_tree(w)  # type: ignore[attr-defined]
    for n in ("c1", "c2", "c3"):
        shutil.rmtree(w.transcript(ID[n]).parent / ID[n])
        w.transcript(ID[n]).unlink()
        shutil.rmtree(w.home / "file-history" / ID[n])
    return w


@pytest.fixture
def wired(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    snapshot = ChainSnapshot((SessionFacts("S1", "t", 1, "local", "stopped", "closed_by_user", False, False, ID["c3"], 1.0),),
                             {ID["c3"]: frozenset({ID["c2"]}), ID["c2"]: frozenset({ID["c1"]})})
    monkeypatch.setattr(restore_routes.session_chains, "read_snapshot", lambda: snapshot)
    monkeypatch.setattr(restore_routes.RUNTIME, "vault", lambda: world.vault)
    monkeypatch.setattr(restore_routes.RUNTIME, "sources", lambda: world.sources)
    return world


def restore_routes_of_router() -> list:
    return [r for r in save_routes.router.routes if r.path.startswith("/cplugs/save/offload/") and r.path.endswith("/restore")]


def forbidden_imports(source: str) -> List[str]:
    bad: List[str] = []
    for node in ast.walk(ast.parse(source)):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module or ""] + [a.name for a in node.names]) if isinstance(node, ast.ImportFrom) else []
        bad += [n for n in names if any(part in n for part in ("save.start", "session_bring_up", "session_actions", "CplugContext", "cplug_context")) or n == "start"]
    return bad


def test_a_session_restore_puts_the_chain_back_exactly_and_never_starts_a_session(wired: World, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[str] = []
    monkeypatch.setattr(start, "start_after_restore", lambda *a, **k: calls.append("start") or None)
    out = restore_routes.run_restore("S1", None, False)
    assert [c.conversation_id for c in out.conversations] == [ID["c3"], ID["c2"], ID["c1"]]
    assert {c.status for c in out.conversations} == {"written"} and out.started_session is False and calls == []
    assert digest_tree(wired) == wired.before  # type: ignore[attr-defined]
    assert stat.S_IMODE(wired.transcript(ID["c1"]).stat().st_mode) == 0o640
    again = restore_routes.run_restore("S1", None, False)
    assert {c.status for c in again.conversations} == {"already_present"} and all(c.written == 0 for c in again.conversations)
    assert len(restore_routes_of_router()) == 2


def test_the_offload_package_cannot_reach_a_session(tmp_path: Path) -> None:
    assert forbidden_imports("from src.plugins.save import start\n") == ["start"]
    assert forbidden_imports("from src.plugins.sdk import CplugContext\n") == ["CplugContext"]
    assert forbidden_imports("import json\nfrom src.plugins.save.vault import restore\n") == []
    found = {p.name: forbidden_imports(p.read_text()) for p in OFFLOAD_DIR.glob("*.py")}
    assert {k: v for k, v in found.items() if v} == {}
    for route in restore_routes_of_router():
        assert {p for p in inspect.signature(route.endpoint).parameters} <= {"session_uuid", "conversation_id", "body"}


def test_a_different_file_is_a_collision_and_nothing_of_that_conversation_is_written(wired: World) -> None:
    main = wired.transcript(ID["c2"])
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_bytes(b"something else entirely\n")
    out = restore_routes.run_restore(None, ID["c2"], False).conversations[0]
    assert out.status == "conflict" and out.conflicts == [str(main)] and out.written == 0
    assert main.read_bytes() == b"something else entirely\n"
    assert not (main.parent / ID["c2"]).exists() and not (wired.home / "file-history" / ID["c2"]).exists()


def test_a_disk_copy_that_grew_past_the_vault_wins(wired: World) -> None:
    main = wired.transcript(ID["c1"])
    main.parent.mkdir(parents=True, exist_ok=True)
    body = b"".join(restore_chain.restore.read_entry(wired.vault.blobs, wired.vault.manifests.newest(ID["c1"]).main())) + b'{"later":1}\n'  # type: ignore[union-attr]
    main.write_bytes(body)
    out = restore_routes.run_restore(None, ID["c1"], False).conversations[0]
    assert out.status == "written" and out.disk_newer == 1 and out.conflicts == [] and main.read_bytes() == body
    assert (main.parent / ID["c1"] / "subagents").exists()


def test_a_damaged_chunk_fails_without_leaving_a_file_behind(wired: World) -> None:
    point = wired.vault.manifests.newest(ID["c3"])
    main = point.main()  # type: ignore[union-attr]
    path, _codec = wired.vault.blobs.find(main.chunks[0].sha256)  # type: ignore[union-attr]
    path.write_bytes(b"garbage that is not a chunk")
    out = restore_routes.run_restore(None, ID["c3"], False).conversations[0]
    assert out.status == "failed" and out.detail
    assert not wired.transcript(ID["c3"]).exists() and list(wired.projects.rglob(".vault-restore-*")) == []


def test_bytes_that_do_not_hash_to_the_points_sha256_are_never_placed(wired: World, monkeypatch: pytest.MonkeyPatch) -> None:
    point = wired.vault.manifests.newest(ID["c2"])
    wrong = replace(point, files=[replace(e, sha256="0" * 64) if e.role == K.ROLE_TRANSCRIPT else e for e in point.files])  # type: ignore[arg-type]
    monkeypatch.setattr(wired.vault.manifests, "newest", lambda unit: wrong)
    out = restore_routes.run_restore(None, ID["c2"], False).conversations[0]
    assert out.status == "failed" and not wired.transcript(ID["c2"]).exists() and list(wired.projects.rglob(".vault-restore-*")) == []


def test_a_dry_run_writes_nothing_and_a_missing_point_or_session_is_named(wired: World) -> None:
    out = restore_routes.run_restore("S1", None, True)
    assert {c.status for c in out.conversations} == {"would_write"} and not any(wired.projects.rglob("*.jsonl"))
    assert restore_routes.run_restore(None, ID["x1"], False).conversations[0].status == "no_vault_point"
    with pytest.raises(HTTPException) as caught:
        restore_routes.run_restore("nope", None, False)
    assert caught.value.status_code == 404
    with pytest.raises(HTTPException) as bad:
        restore_routes.run_restore(None, "../x", False)
    assert bad.value.status_code == 400


def test_an_imported_point_never_restores_the_mode_an_importer_invented(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.write_conversation(jsonl(5), conv=ID["c1"], subagents=0, tool_results=0)
    os.chmod(w.transcript(ID["c1"]), 0o600)
    w.capture(ID["c1"], reason=K.REASON_IMPORT)
    shutil.rmtree(w.transcript(ID["c1"]).parent)
    shutil.rmtree(w.home / "file-history")
    out = restore_chain.restore_conversation(w.vault, ID["c1"], homes(w))
    assert out.status == "written" and stat.S_IMODE(w.transcript(ID["c1"]).stat().st_mode) == 0o644


def _plant_after_first_write(monkeypatch: pytest.MonkeyPatch, plant) -> None:
    real = restore_chain.restore.write_entry
    done: List[bool] = []

    def wrapper(blobs, entry, dest, **kw):
        real(blobs, entry, dest, **kw)
        if entry.role == K.ROLE_TRANSCRIPT and not done:
            done.append(True)
            plant(entry, dest)

    monkeypatch.setattr(restore_chain.restore, "write_entry", wrapper)


def test_a_damaged_side_file_means_nothing_of_the_conversation_is_written(wired: World) -> None:
    point = wired.vault.manifests.newest(ID["c2"])
    side = next(e for e in point.files if e.role == K.ROLE_SUBAGENT)  # type: ignore[union-attr]
    path, _codec = wired.vault.blobs.find(side.chunks[0].sha256)  # type: ignore[arg-type]
    path.write_bytes(b"garbage that is not a chunk")
    out = restore_routes.run_restore(None, ID["c2"], False).conversations[0]
    assert out.status == "failed" and out.written == 0 and "nothing was written" in out.detail
    assert not wired.transcript(ID["c2"]).exists()


def test_the_answer_says_what_is_on_disk_when_a_collision_appears_after_the_main_transcript(wired: World, monkeypatch: pytest.MonkeyPatch) -> None:
    point = wired.vault.manifests.newest(ID["c2"])
    side_dest = {}

    def plant(entry, dest) -> None:
        for other in point.files:  # type: ignore[union-attr]
            if other.role != K.ROLE_TRANSCRIPT:
                target = wired.home / other.rel if other.home == "claude" else None
                target.parent.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
                target.write_bytes(b"someone else's file\n")  # type: ignore[union-attr]
                side_dest[other.rel] = target

    _plant_after_first_write(monkeypatch, plant)
    out = restore_routes.run_restore(None, ID["c2"], False).conversations[0]
    assert out.status == "conflict" and out.written == 1 and wired.transcript(ID["c2"]).exists()
    assert len(out.conflicts) == 1 and out.conflicts[0] in {str(p) for p in side_dest.values()}
    assert all(p.read_bytes() == b"someone else's file\n" for p in side_dest.values() if str(p) in out.conflicts)


def test_a_file_that_grew_while_it_was_restored_is_written_with_a_note_not_failed(wired: World, monkeypatch: pytest.MonkeyPatch) -> None:
    def grow(entry, dest) -> None:
        with open(dest, "ab") as handle:
            handle.write(b'{"resumed":1}\n')

    _plant_after_first_write(monkeypatch, grow)
    out = restore_routes.run_restore(None, ID["c1"], False).conversations[0]
    assert out.status == "written" and out.written == 5 and out.notes == [f"grew_during_restore: {wired.transcript(ID['c1'])}"]
    assert wired.transcript(ID["c1"]).read_bytes().endswith(b'{"resumed":1}\n')


def test_a_file_that_appears_between_plan_and_write_is_compared_and_labelled(wired: World, monkeypatch: pytest.MonkeyPatch) -> None:
    point = wired.vault.manifests.newest(ID["c2"])
    destination = restore_chain.restore.homes_destination(homes(wired))
    by_name = {e.rel.rsplit("/", 1)[-1]: e for e in point.files}  # type: ignore[union-attr]
    real = restore_chain.restore.write_entry
    done: List[bool] = []
    same = b"".join(restore_chain.restore.read_entry(wired.vault.blobs, by_name["agent-0.meta.json"]))
    grown = b"".join(restore_chain.restore.read_entry(wired.vault.blobs, by_name["agent-0.jsonl"])) + b'{"more":1}\n'

    def wrapper(blobs, entry, dest, **kw):
        real(blobs, entry, dest, **kw)
        if not done:
            done.append(True)
            for name, body in (("agent-0.meta.json", same), ("agent-0.jsonl", grown), ("t0.txt", b"different")):
                target = destination(by_name[name])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)

    monkeypatch.setattr(restore_chain.restore, "write_entry", wrapper)
    result = restore_chain.restore.restore_manifest(wired.vault.blobs, point, destination, skip_conflicts=True)  # type: ignore[arg-type]
    names = lambda paths: sorted(p.name for p in paths)  # noqa: E731
    assert names(result.already_present) == ["agent-0.meta.json"] and names(result.disk_newer) == ["agent-0.jsonl"] and names(result.skipped_conflicts) == ["t0.txt"]


from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import routes as host_routes, runtime
from src.cplugs.save.fallback import BackupTranscripts
from src.cplugs.save.vault.location import VaultUnavailable
from src.core.deepsearch import fallback_hook as fb
from src.cplugs.sdk import transcript_files
from tests.python.cplugs.save.vault_helpers import CODEX_ID, CONV, World, jsonl
from tests.python.time_machine.helpers import make_corpus


def _vault_state(root: Path) -> list:
    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*"))


@pytest.fixture
def backed_up(tmp_path: Path):
    from src.cplugs.save.vault import units
    from src.cplugs.save.vault.identity import Identity

    world = World(tmp_path)
    main = world.write_conversation(jsonl(30))
    rollout = world.write_codex(jsonl(20))
    for plan in (units.plan_claude(world.sources, CONV), units.plan_codex(world.sources, CODEX_ID)):
        world.vault.capture(plan, Identity(), "backfill")
    return world, main.read_bytes(), rollout.read_bytes()


def test_it_offers_the_newest_backup_as_range_readable_files_and_writes_nothing(backed_up):
    world, original, rollout = backed_up
    source = BackupTranscripts(lambda: world.vault)
    before = _vault_state(world.vault.root)
    found = {c.conversation_id: c for c in source.conversations()}
    assert {(c.conversation_id, c.family) for c in found.values()} == {(CONV, "claude"), (CODEX_ID, "codex")}
    newest = world.vault.manifests.newest(CONV).main()
    assert found[CONV].signature == newest.sha256 and found[CONV].sha256 is None
    files = source.files(CONV)
    assert [f.file_kind for f in files] == ["conversation", "subagent", "subagent"]
    assert files[0].source_path == str(world.transcript()) and files[0].length == len(original)
    assert all(f.file_kind == "subagent" and "/subagents/" in f.source_path for f in files[1:])
    assert [f.file_kind for f in source.files(CODEX_ID)] == ["conversation"]
    reader = source.reader(CONV, files[0].source_path, "conversation")
    assert reader.length == len(original) and reader.read(10, 40) == original[10:50]
    assert source.reader(CODEX_ID, source.files(CODEX_ID)[0].source_path, "conversation").read(0, 30) == rollout[:30]
    assert _vault_state(world.vault.root) == before


def test_a_file_is_found_by_its_place_when_the_folder_above_is_spelled_differently(backed_up):
    world, original, _rollout = backed_up
    source = BackupTranscripts(lambda: world.vault)
    other = f"/symlinked/home/projects/-Users-x-proj/{CONV}.jsonl"
    assert source.reader(CONV, other, "conversation").read(0, 20) == original[:20]
    sub = next(f for f in source.files(CONV) if f.file_kind == "subagent")
    tail = sub.source_path.split(f"/{CONV}/", 1)[1]
    assert source.reader(CONV, f"/elsewhere/{CONV}/{tail}", "subagent").length == sub.length
    with pytest.raises(fb.FallbackUnavailable):
        source.reader(CONV, f"/elsewhere/{CONV}/subagents/nope.jsonl", "subagent")
    with pytest.raises(fb.FallbackUnavailable):
        source.reader("no-such-conversation-0000", other, "conversation")


def test_a_damaged_chunk_is_unavailable_not_wrong_bytes_and_an_unreachable_vault_is_an_error(backed_up, tmp_path):
    world, _original, _rollout = backed_up
    source = BackupTranscripts(lambda: world.vault)
    entry = world.vault.manifests.newest(CONV).main()
    path, _codec = world.vault.blobs.find(entry.chunks[0].sha256)
    path.write_bytes(b"garbage")
    with pytest.raises(fb.FallbackUnavailable):
        source.reader(CONV, entry.source_path, "conversation").read(0, 10)

    def unreachable():
        raise VaultUnavailable("the vault is on /Volumes/ExampleDrive, which is not mounted")

    with pytest.raises(OSError):
        list(BackupTranscripts(unreachable).conversations())
    with pytest.raises(OSError):
        BackupTranscripts(unreachable).files(CONV)
    assert list(BackupTranscripts(lambda: __import__("src.cplugs.save.vault.store", fromlist=["Vault"]).Vault(tmp_path / "empty")).conversations()) == []


def test_the_boot_flag_defaults_off_raises_on_begin_and_lowers_on_end():
    assert fb.booting() is False
    fb.begin_boot()
    try:
        assert fb.booting() is True
    finally:
        fb.end_boot()
    assert fb.booting() is False
    fb.begin_boot(grace=-1.0)
    assert fb.booting() is False


@pytest.fixture
def rig(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(transcript_files, "state_dir", lambda: state)
    monkeypatch.setattr(transcript_files, "projects_dir", lambda: make_corpus(tmp_path))
    app = FastAPI()
    host = runtime.install(app, state)
    host.publish = lambda *_a, **_k: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    yield app
    asyncio.run(host.stop())


def test_the_source_is_registered_only_while_the_plugin_is_on(rig):
    with TestClient(rig) as client:
        assert fb.sources() == ()
        revision = client.get("/api/v1/cplugs/save").json()["revision"]
        assert client.put("/api/v1/cplugs/save", json={"revision": revision, "enabled": True}).status_code == 200
        assert [type(s) for s in fb.sources()] == [BackupTranscripts]
        revision = client.get("/api/v1/cplugs/save").json()["revision"]
        assert client.put("/api/v1/cplugs/save", json={"revision": revision, "enabled": False}).status_code == 200
        assert fb.sources() == ()


def test_the_host_lowers_the_boot_flag_once_every_plugin_has_started(rig):
    fb.begin_boot()
    assert fb.booting() is True
    asyncio.run(rig.state.cplugs_host.start())
    assert fb.booting() is False


def test_entries_lists_every_role_of_the_newest_point(backed_up):
    world, original, _rollout = backed_up
    source = BackupTranscripts(lambda: world.vault)
    newest = world.vault.manifests.newest(CONV)
    entries = source.entries(CONV)
    assert [(e.role, e.home, e.rel) for e in entries] == [(f.role, f.home, f.rel) for f in newest.files]
    assert {e.role for e in entries} >= {"transcript", "subagent", "tool_result", "file_history"}
    main = next(e for e in entries if e.role == "transcript")
    assert main.length == len(original) and main.signature == newest.main().chain_sha() and main.family == "claude"
    assert source.entries("no-such-conversation-0000") == []
    assert [e.role for e in source.entries(CODEX_ID)] == ["codex_rollout"]


def test_entry_reader_reads_a_tool_result(backed_up):
    world, _original, _rollout = backed_up
    source = BackupTranscripts(lambda: world.vault)
    tool = next(e for e in source.entries(CONV) if e.role == "tool_result")
    data = (world.projects / tool.rel.split("/", 1)[1]).read_bytes() if tool.rel.startswith("projects/") else None
    reader = source.entry_reader(CONV, tool.rel)
    assert data is not None and reader.length == len(data) == tool.length and reader.read(0, reader.length) == data
    with pytest.raises(fb.FallbackUnavailable):
        source.entry_reader(CONV, "projects/-nowhere/none.txt")

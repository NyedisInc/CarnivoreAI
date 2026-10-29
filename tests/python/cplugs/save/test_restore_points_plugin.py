
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import routes as host_routes, runtime
from src.cplugs.sdk import save_triggers, transcript_files, vault_sources
from tests.python.cplugs.save.vault_helpers import stop_follower
from tests.python.time_machine.helpers import CONV, FOLDER, WORKDIR, make_corpus

POINTS = f"/api/v1/cplugs/save/conversations/{CONV}/points"


@pytest.fixture
def rig(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    corpus = make_corpus(tmp_path)
    monkeypatch.setattr(transcript_files, "state_dir", lambda: state)
    monkeypatch.setattr(transcript_files, "projects_dir", lambda: corpus)
    monkeypatch.setattr(vault_sources, "claude_roots", lambda: (corpus,))
    monkeypatch.setattr(vault_sources, "codex_home", lambda: tmp_path / "codex")
    app = FastAPI()
    host = runtime.install(app, state)
    host.publish = lambda *_a, **_k: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    yield app, state, corpus
    asyncio.run(host.stop())


def _kill() -> None:
    save_triggers.announce(save_triggers.LifecycleSave(
        event="kill", conversation_id=CONV, session_uuid="sess-uuid-1", family="claude",
        facts={"working_dir": WORKDIR, "project_name": "My Project", "wrapper": "claude"}))


def _switch(client: TestClient, enabled: bool) -> None:
    revision = client.get("/api/v1/cplugs/save").json()["revision"]
    answer = client.put("/api/v1/cplugs/save", json={"revision": revision, "enabled": enabled})
    assert answer.status_code == 200, answer.text
    if enabled:
        stop_follower(client)


def _tree_points(state: Path) -> list:
    root = state / "vault" / "manifests"
    return [p for p in root.glob("*/*.json")] if root.is_dir() else []


def test_on_captures_lists_and_restores_and_the_start_waits_for_its_grant(rig):
    app, state, corpus = rig
    with TestClient(app) as client:
        assert client.get("/api/v1/cplugs/save").json()["enabled"] is False
        _switch(client, True)
        _kill()
        listed = client.get(POINTS)
        assert listed.status_code == 200, listed.text
        points = listed.json()["points"]
        assert len(points) == 1 and points[0]["reason"] == "kill"
        transcript = corpus / FOLDER / f"{CONV}.jsonl"
        original = transcript.read_bytes()
        transcript.unlink()
        restored = client.post(f"{POINTS}/{points[0]['id']}/restore", json={})
        assert restored.status_code == 200, restored.text
        body = restored.json()
        assert body["transcript_status"] == "written" and transcript.read_bytes() == original
        assert body["session"]["status"] == "refused" and body["session"]["code"] == "grant_needed"
        assert "sessions.create" in body["session"]["detail"]


def test_off_answers_409_and_captures_nothing(rig):
    app, state, _corpus = rig
    with TestClient(app) as client:
        refused = client.get(POINTS)
        assert refused.status_code == 409 and refused.json()["detail"]["code"] == "cplug_disabled"
        _kill()
        assert _tree_points(state) == []
        _switch(client, True)
        _kill()
        assert len(_tree_points(state)) == 1
        _switch(client, False)
        _kill()
        assert len(_tree_points(state)) == 1
        assert client.get(POINTS).status_code == 409


def test_the_manifest_asks_the_start_grant_and_grants_nothing_itself(rig):
    app, _state, _corpus = rig
    with TestClient(app) as client:
        row = client.get("/api/v1/cplugs/save").json()
        assert "sessions.create" in row["permissions"]["app"]
        assert row["grants"]["app"] == []

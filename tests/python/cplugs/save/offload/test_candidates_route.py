
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.plugins.save.offload import routes as offload_routes
from src.plugins.sdk import session_chains as sdk
from src.plugins.sdk.session_chains import ChainSnapshot, RunningScan, SessionFacts
from tests.python.cplugs.save.vault_helpers import World, jsonl

CONV = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    world = World(tmp_path)
    os.chmod(world.state, 0o700)
    monkeypatch.setattr(sdk, "read_running", lambda: RunningScan(frozenset(), 0))
    monkeypatch.setattr(offload_routes.RUNTIME, "vault", lambda: world.vault)
    monkeypatch.setattr(offload_routes.RUNTIME, "sources", lambda: world.sources)
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    monkeypatch.setattr(sdk, "read_snapshot", lambda: ChainSnapshot((), {}))
    router = APIRouter()
    offload_routes.add_to(router)
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    c.world = world  # type: ignore[attr-defined]
    return c


def test_candidates_empty_when_no_session_exists(client: TestClient) -> None:
    body = client.get("/offload/candidates").json()
    assert body["candidates"] == [] and body["total"] == 0 and body["next_cursor"] is None
    assert body["readiness"] == {"ready": True, "blockers": []} and body["idle_days"] == 30
    assert body["offloadable"] == {"sessions": 0, "conversations": 0, "bytes": 0}


def test_candidates_lists_an_idle_captured_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    world = client.world  # type: ignore[attr-defined]
    world.write_conversation(jsonl(5, seed=1), conv=CONV, subagents=0, tool_results=0)
    old = time.time() - 3 * 86400
    for path in [p for p in world.home.rglob("*") if p.is_file()]:
        os.utime(path, (old, old))
    world.capture(CONV)
    snap = ChainSnapshot((SessionFacts("S1", "my title", 1, "local", "stopped", "closed_by_user", False, False, CONV, old),), {})
    monkeypatch.setattr(sdk, "read_snapshot", lambda: snap)
    resp = client.get("/offload/candidates", params={"idle_days": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1 and body["offloadable"]["sessions"] == 1 and body["offloadable"]["conversations"] == 1
    row = body["candidates"][0]
    assert row["session_uuid"] == "S1" and row["title"] == "my title" and row["conversations"] == 1 and row["shared"] is False
    assert row["bytes"] > 0 and row["bytes"] == body["offloadable"]["bytes"] and row["idle_days"] >= 3


def test_candidates_rejects_a_bad_cursor(client: TestClient) -> None:
    assert client.get("/offload/candidates", params={"cursor": "zzz"}).status_code == 400

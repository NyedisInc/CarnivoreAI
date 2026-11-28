
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import offloaded_routes
from src.api.auth import require_auth
from src.core.backup_health import offload_guard, offloaded_marker
from src.core.deepsearch import fallback_hook

WHEN = 1_762_000_000.0


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(offload_guard, "_state_dir", lambda: tmp_path)
    fallback_hook.unregister(offload_guard.SAVE_SOURCE_ID)
    fallback_hook.end_boot()
    app = FastAPI()
    app.include_router(offloaded_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as c:
        yield SimpleNamespace(http=c, state=tmp_path)
    fallback_hook.unregister(offload_guard.SAVE_SOURCE_ID)


def mark(state, rows, times) -> None:
    assert offloaded_marker.write(state, rows, times)


def test_a_session_answers_every_conversation_it_went_out_with_summed(client) -> None:
    mark(client.state, [("c1", ["S1"], 1000), ("c2", ["S1", "S2"], 500), ("c3", ["S9"], 77)], {"c1": WHEN, "c2": WHEN + 60})
    body = client.http.get("/api/v1/offloaded", params={"session_uuid": "S1"}).json()
    assert body["conversations"] == ["c1", "c2"] and body["bytes"] == 1500 and body["offloaded_at"] == WHEN + 60
    assert body["code"] == "offloaded" and body["plugin_on"] is False and "turn backups on" in body["detail"] and body["unreadable"] is False
    assert "{session_uuid}" in body["restore_route"]


def test_one_conversation_answers_by_id_and_plugin_on_changes_the_sentence(client) -> None:
    mark(client.state, [("c1", [], 1000)], {})
    fallback_hook.register(offload_guard.SAVE_SOURCE_ID, SimpleNamespace())
    body = client.http.get("/api/v1/offloaded", params={"conversation_id": "c1"}).json()
    assert body["plugin_on"] is True and "restore it first" in body["detail"] and body["offloaded_at"] == 0.0


def test_nothing_offloaded_is_404_and_no_id_is_400_and_a_broken_marker_answers_unreadable(client) -> None:
    assert client.http.get("/api/v1/offloaded", params={"session_uuid": "S1"}).status_code == 404
    assert client.http.get("/api/v1/offloaded").status_code == 400
    (client.state / offloaded_marker.MARKER_FILE).write_text("{broken")
    body = client.http.get("/api/v1/offloaded", params={"session_uuid": "S1"}).json()
    assert body["unreadable"] is True and body["bytes"] == 0


def test_a_respawn_refused_offloaded_answers_the_code_and_the_session_uuid_it_resolved() -> None:
    import asyncio

    from src.api.session_attach_routes import respawn_session
    from src.models.restart import RespawnSessionRequest

    async def respawn(name, **_kw):
        return {"name": name, "kind": "offloaded", "ok": False, "detail": "offloaded", "session_uuid": "S1"}

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=SimpleNamespace(respawn_session=respawn))))
    out = asyncio.run(respawn_session(request, RespawnSessionRequest(session_name="carnivore_x")))
    assert (out.code, out.session_uuid, out.ok) == ("offloaded", "S1", False)
    plain = {"name": "n", "kind": "agent", "ok": True, "detail": ""}

    async def respawn_ok(name, **_kw):
        return plain

    request.app.state.session_manager.respawn_session = respawn_ok
    assert asyncio.run(respawn_session(request, RespawnSessionRequest(session_name="n"))).code is None

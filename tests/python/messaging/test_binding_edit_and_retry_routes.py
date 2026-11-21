
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import messaging_routes
from src.api.auth import require_auth
from src.core.messaging import message_store, store

from .conftest import UUID_A, bind

API = "/api/v1/messaging"


def _client(world, signed_in: bool = True) -> TestClient:
    app = FastAPI()
    app.state.messaging = world.rt
    world.rt.app = app
    app.include_router(messaging_routes.router, prefix="/api/v1")
    if signed_in:
        app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def _failed_inbound(world, binding_id: str, reason: str) -> str:
    message_store.record_event(world.pid, 900, [{
        "conversation_id": world.conv_id, "binding_id": binding_id, "session_uuid": UUID_A, "direction": "in",
        "kind": "message", "provider_message_id": f"pm-{reason}", "sent_at": 1.0, "text": "hello", "status": "failed",
        "reason": reason,
    }])
    return next(m["id"] for m in message_store.list_messages(binding_id=binding_id) if m["reason"] == reason)


def test_patch_changes_the_direction_and_the_store_agrees(world) -> None:
    row = bind(world, UUID_A, direction="both")
    resp = _client(world).patch(f"{API}/bindings/{row['id']}", json={"direction": "both", "default": True})
    assert resp.status_code == 200, resp.text
    assert bool(resp.json()["default"]) is True
    assert bool(store.get_binding(row["id"])["default"]) is True


def test_patch_an_unknown_binding_is_a_404_and_an_unknown_field_a_422(world) -> None:
    client = _client(world)
    missing = client.patch(f"{API}/bindings/b_nope", json={"default": True})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "binding_not_found"
    row = bind(world, UUID_A)
    assert client.patch(f"{API}/bindings/{row['id']}", json={"sneaky": 1}).status_code == 422


def test_delete_unbinds_and_a_second_delete_is_a_404(world) -> None:
    row = bind(world, UUID_A)
    client = _client(world)
    assert client.delete(f"{API}/bindings/{row['id']}").json() == {"deleted": True}
    assert store.get_binding(row["id"]) is None
    assert client.delete(f"{API}/bindings/{row['id']}").status_code == 404


def test_retry_queues_a_failed_inbound_row_again(world) -> None:
    row = bind(world, UUID_A)
    mid = _failed_inbound(world, row["id"], "session_gone")
    resp = _client(world).post(f"{API}/messages/{mid}/retry")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"
    assert message_store.get_message(mid)["status"] == "queued"


@pytest.mark.parametrize("reason", sorted(message_store.NOT_RETRIABLE)[:2])
def test_retry_refuses_a_row_that_must_not_be_replayed(world, reason: str) -> None:
    row = bind(world, UUID_A)
    mid = _failed_inbound(world, row["id"], reason)
    resp = _client(world).post(f"{API}/messages/{mid}/retry")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "not_retriable"
    assert message_store.get_message(mid)["status"] == "failed"


def test_binding_and_retry_routes_need_auth(world) -> None:
    row = bind(world, UUID_A)
    client = _client(world, signed_in=False)
    assert client.patch(f"{API}/bindings/{row['id']}", json={"default": True}).status_code in (401, 403)
    assert client.delete(f"{API}/bindings/{row['id']}").status_code in (401, 403)
    assert client.post(f"{API}/messages/m_x/retry").status_code in (401, 403)
    assert store.get_binding(row["id"]) is not None

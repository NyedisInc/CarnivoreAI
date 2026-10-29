
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import messaging_agent_routes, messaging_routes, session_input_routes
from src.api.agent_auth import require_agent
from src.api.auth import require_auth
from src.core.mcp.caller import AgentCaller
from src.core.messaging import store

from .conftest import CONV, OTHER_CONV, UUID_A, UUID_B, bind, screen

PANE_A = AgentCaller(session_id="ses_a", tmux_name="cloude_trader", current_session_id="ses_a")


def _client(world, caller: AgentCaller = PANE_A) -> TestClient:
    app = FastAPI()
    app.state.session_manager = world.manager
    app.state.messaging = world.rt
    world.rt.app = app
    app.include_router(messaging_routes.router, prefix="/api/v1")
    app.include_router(messaging_agent_routes.router, prefix="/api/v1")
    app.include_router(session_input_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[require_agent] = lambda: caller
    return TestClient(app)


def _send(client, session_id="ses_a", **body):
    return client.post(f"/api/v1/sessions/{session_id}/messaging/send", json={"text": "build is green", **body})


def test_messaging_send_from_an_unbound_session_is_403_and_nothing_reaches_the_provider(world):
    bind(world, UUID_B)
    response = _send(_client(world))
    assert response.status_code == 403 and response.json()["detail"]["code"] == "not_bound"
    assert world.provider.sent == []


def test_an_in_only_binding_cannot_text_back(world):
    bind(world, UUID_A, direction="in")
    response = _send(_client(world))
    assert response.status_code == 403 and world.provider.sent == []


def test_an_owner_minted_external_token_is_refused(world):
    bind(world, UUID_A)
    external = AgentCaller(session_id="mcp-token:t1", tmux_name="mcp-token:t1", current_session_id="mcp-token:t1",
                           token_name="laptop")
    response = _send(_client(world, external), session_id="mcp-token:t1")
    assert response.status_code == 403 and world.provider.sent == []


def test_a_bound_session_sends_audit_first_with_secrets_starred(world):
    bind(world, UUID_A)
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    response = _send(_client(world), text=f"done, token was {secret}")
    assert response.status_code == 201, response.text
    assert response.json()["scrubbed"] is True
    assert len(world.provider.sent) == 1 and secret not in world.provider.sent[0]["text"]
    assert world.provider.sent[0]["client_ref"] == response.json()["message_id"]


def test_a_token_for_one_session_cannot_post_to_anothers_path(world):
    bind(world, UUID_B)
    response = _send(_client(world), session_id="ses_b")
    assert response.status_code == 403 and response.json()["detail"]["code"] == "not_your_session"


def test_binding_refuses_a_conversation_the_provider_does_not_list_as_routable(world):
    client = _client(world)
    refused = client.post("/api/v1/messaging/conversations",
                          json={"provider_id": world.pid, "conversation": OTHER_CONV, "label": "someone"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "not_routable"
    ok = client.post("/api/v1/messaging/bindings",
                     json={"conversation_id": world.conv_id, "session_uuid": UUID_A, "direction": "both"})
    assert ok.status_code == 201, ok.text
    world.provider.listed = [e for e in world.provider.listed if e.conversation != CONV]
    again = client.post("/api/v1/messaging/bindings",
                        json={"conversation_id": world.conv_id, "session_uuid": UUID_B, "direction": "in"})
    assert again.status_code == 422 and again.json()["detail"]["code"] == "not_routable"
    assert [b["session_uuid"] for b in store.list_bindings()] == [UUID_A]


def test_binding_refuses_an_unknown_field_and_never_answers_a_secret(world):
    client = _client(world)
    bad = client.post("/api/v1/messaging/bindings", json={"conversation_id": world.conv_id, "session_uuid": UUID_A,
                                                           "direction": "both", "sneaky": 1})
    assert bad.status_code == 422
    body = client.get("/api/v1/messaging/providers").text + client.get("/api/v1/messaging/conversations").text
    for secret in ("tok-not-real", "10.9.9.9", "+15165550100", CONV):
        assert secret not in body


@pytest.fixture
def command_client(world):
    client = _client(world)
    registry = SimpleNamespace(resolve_session_id=lambda sid: sid or "ses_a")
    client.app.state.services = SimpleNamespace(registry=registry)
    return client


def test_sessions_command_into_a_pane_with_a_dialog_is_409_and_the_pane_is_unchanged(world, command_client):
    world.screens["cloude_trader"] = screen("claude_permission")
    response = command_client.post("/api/v1/sessions/command", json={"command": "yes"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "pane_dialog_open"
    assert world.manager.commands == []


def test_sessions_command_into_an_unreadable_agent_pane_is_409(world, command_client):
    world.screens.pop("cloude_trader")
    response = command_client.post("/api/v1/sessions/command", json={"command": "ls"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "dialog_unreadable"
    assert world.manager.commands == []


def test_sessions_command_into_a_clear_pane_or_a_plain_shell_still_works(world, command_client):
    assert command_client.post("/api/v1/sessions/command", json={"command": "ls"}).status_code == 200
    world.manager.infos["ses_a"].agent_family = None
    world.screens.pop("cloude_trader")
    assert command_client.post("/api/v1/sessions/command", json={"command": "pwd"}).status_code == 200
    assert world.manager.commands == ["ls", "pwd"]

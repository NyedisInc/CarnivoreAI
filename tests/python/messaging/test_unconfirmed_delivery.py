
from __future__ import annotations

import asyncio
import json

from fastapi import HTTPException

from src.api import messaging_agent_routes as routes
from src.core.messaging import client, message_store
from src.core.notifications import http

from .conftest import UUID_A, bind


def _restart_mid_send(monkeypatch, world) -> HTTPException:
    async def fake(method, url, **kw):
        body = {"error": "send_in_doubt", "detail": "Restarted mid-send."}
        return http.GuardResponse(422, {}, json.dumps(body).encode(), False)

    async def identity(request, caller):
        return UUID_A, "trader"

    monkeypatch.setattr(client.http, "guarded_request", fake)
    monkeypatch.setattr(routes, "_caller_identity", identity)
    monkeypatch.setattr(routes, "runtime_of", lambda request: world.rt)
    world.rt.providers[world.pid].client = client.HttpProviderClient(
        "p_x", "http://10.0.0.1:1", "tok-not-real", allow_private=True, allow_plain_http=True)
    bind(world, UUID_A, default=True)
    caller = routes.AgentCaller(session_id="ses_a", tmux_name="t", current_session_id="ses_a", scope="write")
    try:
        asyncio.run(routes.send_for_caller(None, caller, routes.SendBody(text="hi")))
    except HTTPException as exc:
        return exc
    raise AssertionError("the send was expected to be refused as uncertain")


def test_a_mid_send_restart_writes_unconfirmed_and_keeps_the_do_not_resend_reason(world, monkeypatch):
    exc = _restart_mid_send(monkeypatch, world)
    assert exc.status_code == 409 and exc.detail["code"] == "send_uncertain"
    [row] = message_store.list_messages(limit=10)
    assert (row["direction"], row["status"]) == ("out", "unconfirmed")
    assert row["reason"] == "may have been sent; do not resend: Restarted mid-send."


def test_a_plain_provider_failure_stays_failed(world, monkeypatch):
    err = client.ProviderError(client.UNREACHABLE)
    assert err.log_status == "failed"
    assert client.ProviderError(client.UNCERTAIN).log_status == "unconfirmed"


def test_unconfirmed_is_never_retriable(world, monkeypatch):
    _restart_mid_send(monkeypatch, world)
    [row] = message_store.list_messages(limit=10)
    assert message_store.retry(row["id"]) is None
    assert message_store.get_message(row["id"])["status"] == "unconfirmed"

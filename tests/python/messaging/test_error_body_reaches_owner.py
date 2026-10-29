
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from src.api import messaging_routes
from src.core.messaging import client, message_store, notices, outbound
from src.core.notifications import http

from .conftest import UUID_A, bind

TOKEN = "tok-not-real"
SENTENCES = {
    403: "That conversation is protected on the bridge and can't be messaged.",
    413: "That text is longer than the bridge will send.",
    422: "The bridge could not understand that request.",
    503: "The bridge is still starting up; try again in a minute.",
}


def _provider(monkeypatch, status: int, body: dict) -> client.HttpProviderClient:
    async def fake(method, url, **kw):
        return http.GuardResponse(status, {}, json.dumps(body).encode(), False)

    monkeypatch.setattr(client.http, "guarded_request", fake)
    return client.HttpProviderClient("p_x", "http://10.0.0.1:1", TOKEN, allow_private=True, allow_plain_http=True)


def _failed_reasons() -> list:
    return [r["reason"] for r in message_store.list_messages(limit=50) if r["status"] == "failed"]


def _probe_body(world, cli) -> dict:
    world.rt.client_factory = lambda row, secrets: cli
    with pytest.raises(HTTPException) as exc:
        asyncio.run(messaging_routes._probe(world.rt, {}, None))
    return exc.value.detail


@pytest.mark.parametrize("status", sorted(SENTENCES))
def test_the_providers_sentence_reaches_send_probe_and_notice(world, monkeypatch, status):
    sentence = SENTENCES[status]
    cli = _provider(monkeypatch, status, {"error": "some_code", "detail": sentence})
    state = world.rt.providers[world.pid]
    state.client = cli
    bind(world, UUID_A, default=True)

    with pytest.raises(outbound.SendRefused):
        asyncio.run(outbound.send_as_session(world.rt, session_uuid=UUID_A, session_name="trader", text="hi"))
    assert _failed_reasons()[0].endswith(sentence)

    assert _probe_body(world, cli)["reason"] == sentence

    assert asyncio.run(world.rt.send_notice(state, world.conv_id, notices.GAP, None, start="a", end="b")) is False
    assert _failed_reasons()[0].endswith(sentence)
    assert sum(r.endswith(sentence) for r in _failed_reasons()) == 2


def test_an_error_only_body_falls_back_to_the_code(world, monkeypatch):
    cli = _provider(monkeypatch, 403, {"error": "refused"})
    world.rt.providers[world.pid].client = cli
    bind(world, UUID_A, default=True)
    with pytest.raises(outbound.SendRefused):
        asyncio.run(outbound.send_as_session(world.rt, session_uuid=UUID_A, session_name="trader", text="hi"))
    assert _failed_reasons()[0] == "refused"
    assert _probe_body(world, cli)["reason"] == "refused"

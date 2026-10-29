
from __future__ import annotations

import asyncio
import json

import pytest

from src.api import messaging_agent_routes as agent_routes
from src.core.messaging import client, message_store, store
from src.core.notifications import http

from .conftest import UUID_A, bind
from .test_routes import _client

OK = json.dumps({"message_id": "g-1", "status": "sent", "sent_at": "2026-10-13T12:00:00Z"}).encode()


def _wire(monkeypatch, world, steps):
    calls = []

    async def fake(method, url, **kw):
        calls.append(kw["headers"]["idempotency-key"])
        step = steps[len(calls) - 1]
        if step is None:
            raise http.GuardTimeout("timeout")
        return http.GuardResponse(200, step, OK, False)

    monkeypatch.setattr(client.http, "guarded_request", fake)
    world.rt.providers[world.pid].client = client.HttpProviderClient(
        "p_x", "http://10.0.0.1:1", "tok-not-real", allow_private=True, allow_plain_http=True)
    bind(world, UUID_A, default=True)
    return calls


def _send(monkeypatch, world) -> dict:
    async def identity(request, caller):
        return UUID_A, "trader"

    monkeypatch.setattr(agent_routes, "_caller_identity", identity)
    monkeypatch.setattr(agent_routes, "runtime_of", lambda request: world.rt)
    caller = agent_routes.AgentCaller(session_id="ses_a", tmux_name="t", current_session_id="ses_a", scope="write")
    return asyncio.run(agent_routes.send_for_caller(None, caller, agent_routes.SendBody(text="hi")))


def _card(world) -> dict:
    [provider] = _client(world).get("/api/v1/messaging/providers").json()["providers"]
    return provider


def test_a_provider_never_retried_reads_never_seen(world):
    assert _card(world)["idempotency"] == {"proven": False, "last_proven_at": None}


def test_a_retry_answered_with_the_replay_header_is_proven_with_when(world, monkeypatch):
    keys = _wire(monkeypatch, world, [None, {"idempotent-replayed": "true"}])
    _send(monkeypatch, world)
    assert len(keys) == 2 and keys[0] == keys[1]
    idem = _card(world)["idempotency"]
    assert idem["proven"] is True and idem["last_proven_at"] > 0
    assert store.get_provider(world.pid)["replay_proven_at"] == idem["last_proven_at"]


@pytest.mark.parametrize("steps", [
    [None, {}],
    [None, {"idempotent-replayed": "false"}],
    [{"idempotent-replayed": "true"}],
])
def test_anything_short_of_a_marked_retry_proves_nothing(world, monkeypatch, steps):
    _wire(monkeypatch, world, steps)
    _send(monkeypatch, world)
    assert _card(world)["idempotency"] == {"proven": False, "last_proven_at": None}


def test_the_newest_proof_wins_and_an_older_one_never_replaces_it(world):
    message_store.record_replay_proof(world.pid, at=2_000.0)
    message_store.record_replay_proof(world.pid, at=1_000.0)
    assert _card(world)["idempotency"] == {"proven": True, "last_proven_at": 2_000.0}


def test_is_replay_answer_reads_only_the_true_header():
    assert client.is_replay_answer({"idempotent-replayed": " True "}) is True
    assert client.is_replay_answer({"idempotent-replayed": "yes"}) is False
    assert client.is_replay_answer({}) is False
    assert client.is_replay_answer(None) is False

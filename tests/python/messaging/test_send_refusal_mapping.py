
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from src.api import messaging_agent_routes as routes
from src.core.mcp.write_tools import _detail
from src.core.messaging import client, message_store, store
from src.core.notifications import http

from .conftest import UUID_A, bind

REFUSALS = ("That conversation is protected on the bridge and can't be messaged.",
            "The bridge only sends as a bot to this chat; ask the owner to switch identity.")


def _wire(monkeypatch, world, status: int, body: dict, headers: dict | None = None) -> None:
    async def fake(method, url, **kw):
        return http.GuardResponse(status, headers or {}, json.dumps(body).encode(), False)

    monkeypatch.setattr(client.http, "guarded_request", fake)
    world.rt.providers[world.pid].client = client.HttpProviderClient(
        "p_x", "http://10.0.0.1:1", "tok-not-real", allow_private=True, allow_plain_http=True)
    if not store.list_bindings(session_uuid=UUID_A):
        bind(world, UUID_A, default=True)


def _send(monkeypatch, world) -> HTTPException:
    async def identity(request, caller):
        return UUID_A, "trader"

    monkeypatch.setattr(routes, "_caller_identity", identity)
    monkeypatch.setattr(routes, "runtime_of", lambda request: world.rt)
    caller = routes.AgentCaller(session_id="ses_a", tmux_name="t", current_session_id="ses_a", scope="write")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.send_for_caller(None, caller, routes.SendBody(text="hi")))
    return exc.value


@pytest.mark.parametrize("sentence", REFUSALS)
def test_a_403_refusal_keeps_status_code_and_any_sentence(world, monkeypatch, sentence):
    _wire(monkeypatch, world, 403, {"error": "refused", "detail": sentence})
    exc = _send(monkeypatch, world)
    assert (exc.status_code, exc.detail) == (403, {"code": "provider_refused", "reason": sentence})
    assert _detail(exc) == f"refused (403): provider_refused: {sentence}"


@pytest.mark.parametrize("status,code", [(404, "unknown_conversation"), (413, "text_too_long"),
                                         (409, "provider_rejected"), (422, "provider_rejected")])
def test_other_permanent_4xx_keep_the_providers_status(world, monkeypatch, status, code):
    _wire(monkeypatch, world, status, {"error": "x", "detail": f"sentence {status}"})
    exc = _send(monkeypatch, world)
    assert (exc.status_code, exc.detail) == (status, {"code": code, "reason": f"sentence {status}"})


def test_a_provider_401_is_our_credential_problem_so_a_502(world, monkeypatch):
    _wire(monkeypatch, world, 401, {"error": "unauthorized", "detail": "bad token"})
    exc = _send(monkeypatch, world)
    assert (exc.status_code, exc.detail["code"]) == (502, "provider_unauthorized")


def test_transient_failures_stay_gateway_errors(world, monkeypatch):
    _wire(monkeypatch, world, 500, {"error": "boom"})
    exc = _send(monkeypatch, world)
    assert (exc.status_code, exc.detail) == (502, {"code": "provider_unreachable"})
    _wire(monkeypatch, world, 503, {"detail": "starting up"})
    exc = _send(monkeypatch, world)
    assert (exc.status_code, exc.detail) == (503, {"code": "not_ready", "reason": "starting up"})
    _wire(monkeypatch, world, 429, {"detail": "slow down"}, {"retry-after": "30"})
    exc = _send(monkeypatch, world)
    assert (exc.status_code, exc.headers) == (429, {"Retry-After": "30"})


def test_a_200_character_detail_is_cut_with_a_visible_ellipsis_inside_the_cap(world, monkeypatch):
    long = "x" * 200
    snippet = client.error_snippet(json.dumps({"detail": long}).encode())
    assert len(snippet) == client.MAX_DETAIL_CHARS and snippet.endswith("...")
    assert client.error_snippet(json.dumps({"detail": "y" * client.MAX_DETAIL_CHARS}).encode()) == "y" * client.MAX_DETAIL_CHARS
    _wire(monkeypatch, world, 403, {"detail": long})
    assert _send(monkeypatch, world).detail["reason"] == snippet


def test_the_failed_log_row_stores_the_reason_the_screen_renders(world, monkeypatch):
    _wire(monkeypatch, world, 403, {"error": "refused", "detail": REFUSALS[0]})
    _send(monkeypatch, world)
    row = [r for r in message_store.list_messages(limit=50) if r["status"] == "failed"][0]
    assert row["reason"] == REFUSALS[0]


def test_a_failure_with_no_sentence_logs_the_code(world, monkeypatch):
    _wire(monkeypatch, world, 500, {})
    _send(monkeypatch, world)
    row = [r for r in message_store.list_messages(limit=50) if r["status"] == "failed"][0]
    assert row["reason"] == "provider_unreachable"


@pytest.mark.parametrize("status,error", [(422, "send_in_doubt"), (409, "in_progress")])
def test_in_doubt_and_in_progress_are_uncertain_retried_with_the_same_key_and_not_resent(
        world, monkeypatch, status, error):
    keys = []

    async def fake(method, url, **kw):
        keys.append(kw["headers"]["idempotency-key"])
        return http.GuardResponse(status, {}, json.dumps({"error": error, "detail": "Restarted mid-send."}).encode(),
                                  False)

    _wire(monkeypatch, world, status, {})
    monkeypatch.setattr(client.http, "guarded_request", fake)
    exc = _send(monkeypatch, world)
    assert len(keys) == 2 and keys[0] == keys[1]
    assert exc.status_code == 409
    assert exc.detail == {"code": "send_uncertain",
                          "reason": "may have been sent; do not resend: Restarted mid-send."}
    assert message_store.list_messages(status="failed") == []
    [row] = message_store.list_messages(status="unconfirmed")
    assert row["direction"] == "out"
    assert row["reason"] == "may have been sent; do not resend: Restarted mid-send."


@pytest.mark.parametrize("error,detail", [
    ("no_conversation", "No conversation given."),
    ("invalid_request", "Bad request: no conversation given. Nothing was sent."),
    ("idempotency_mismatch", "This retry reused an earlier message's key with different text. Not sent."),
])
def test_other_422_codes_stay_provider_rejected(error, detail):
    err = client._error_for(422, {}, json.dumps({"error": error, "detail": detail}).encode())
    assert (err.code, err.detail) == ("provider_rejected", detail)


def test_uncertain_without_a_sentence_still_says_do_not_resend():
    err = client._error_for(422, {}, b'{"error": "send_in_doubt"}')
    assert err.code == "send_uncertain" and err.owner_text.startswith("may have been sent; do not resend")

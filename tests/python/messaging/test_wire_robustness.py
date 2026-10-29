
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.core.messaging import client, contract, events, stream
from src.core.notifications import http

from .conftest import UUID_A, bind, received, rows

TOKEN = "tok-not-real"


def _good(event_id: int, text: str = "hello") -> dict:
    return {"id": event_id, "type": "message.received", "ts": None, "message": {
        "message_id": f"g{event_id}", "conversation": "any;-;+15165550100", "sender": "+15165550100",
        "identity": "strong", "text": text}}



@pytest.mark.parametrize("bad", [[], {}, ["strong"], {"a": 1}])
def test_a_non_string_max_identity_is_a_contract_error_not_a_type_error(bad):
    caps = {"cpp": 1, "provider": "p", "send": True, "receive": True, "max_identity": bad}
    with pytest.raises(contract.ContractError):
        contract.parse_capabilities(caps)


@pytest.mark.parametrize("bad", [[], {}, ["strong"]])
def test_a_non_string_message_identity_is_a_contract_error_and_the_stream_survives(world, bad):
    frame = _good(1)
    frame["message"]["identity"] = bad
    with pytest.raises(contract.ContractError):
        contract.parse_event(frame)
    state = world.rt.providers[world.pid]

    async def frames():
        yield json.dumps({"type": "hello", "cpp": 1, "after": 0, "oldest": 0, "latest": 0, "gap": False})
        yield json.dumps(frame)
        yield json.dumps(_good(2))

    asyncio.run(stream.consume(world.rt, state, frames()))
    assert state.row["cursor"] == 2



def test_one_malformed_event_is_skipped_counted_and_the_rest_of_the_page_is_processed(world, caplog):
    bind(world, UUID_A, default=True)
    bad = _good(2, text="SECRET-BODY")
    bad["message"]["in_reply_to"] = ""
    page = contract.parse_events_page({"events": [_good(1), bad, _good(3)], "oldest": 0, "latest": 3, "gap": False})
    assert [type(i).__name__ for i in page.events] == ["Event", "SkippedEvent", "Event"]
    state = world.rt.providers[world.pid]
    for item in page.events:
        asyncio.run(events.handle_item(world.rt, state, item))
    assert state.row["cursor"] == 3 and state.extra[events.SKIPPED_KEY] == 1
    assert [r["event_id"] for r in rows()] == [1, 3]
    assert "SECRET-BODY" not in caplog.text


def test_a_malformed_unsend_still_drops_the_held_original_so_it_is_never_delivered_stale(world):
    bind(world, UUID_A, default=True)
    state = world.rt.providers[world.pid]
    asyncio.run(events.handle_event(world.rt, state, received(1, "send the thing", message_id="m1")))
    unsent = {"id": 2, "type": "message.unsent", "ts": "not-a-time", "message": {
        "message_id": "m1", "conversation": "any;-;+15165550100", "sender": "+15165550100", "identity": "strong"}}
    item = contract.parse_event_or_skip(unsent)
    assert isinstance(item, contract.SkippedEvent) and item.event_id == 2
    asyncio.run(events.handle_item(world.rt, state, item))
    assert state.row["cursor"] == 2
    assert [(r["status"], r["reason"]) for r in rows() if r["provider_message_id"] == "m1"] == [("failed", "unsent")]


def test_an_event_with_no_usable_id_is_skipped_without_moving_the_cursor():
    item = contract.parse_event_or_skip({"id": "x", "type": "message.received"})
    assert isinstance(item, contract.SkippedEvent) and item.event_id is None



def _client(monkeypatch, status: int, body: bytes = b"", answers=None):
    calls = []

    async def fake(method, url, **kw):
        calls.append(kw["headers"])
        if answers:
            return answers.pop(0)
        return http.GuardResponse(status, {}, body, False)

    monkeypatch.setattr(client.http, "guarded_request", fake)
    return client.HttpProviderClient("p_x", "http://10.0.0.1:1", TOKEN, allow_private=True, allow_plain_http=True), calls


@pytest.mark.parametrize("status", [400, 409, 422])
def test_a_4xx_is_provider_rejected_with_the_providers_reason(monkeypatch, status):
    cli, _ = _client(monkeypatch, status, json.dumps({"error": "protected chat " + "x" * 500}).encode())
    with pytest.raises(client.ProviderError) as exc:
        asyncio.run(cli.send("c", "hi", reply_to=None, client_ref="r1"))
    assert exc.value.code == client.REJECTED and exc.value.status == status
    assert exc.value.detail.startswith("protected chat") and len(exc.value.detail) <= client.MAX_DETAIL_CHARS


def test_the_providers_reason_never_carries_the_token_and_a_5xx_stays_unreachable(monkeypatch):
    cli, _ = _client(monkeypatch, 422, json.dumps({"message": f"bad {TOKEN}"}).encode())
    with pytest.raises(client.ProviderError) as exc:
        asyncio.run(cli.send("c", "hi", reply_to=None, client_ref="r1"))
    assert TOKEN not in exc.value.detail
    cli, _ = _client(monkeypatch, 502, b'{"error": "boom"}')
    with pytest.raises(client.ProviderError) as exc:
        asyncio.run(cli.send("c", "hi", reply_to=None, client_ref="r1"))
    assert exc.value.code == client.UNREACHABLE and exc.value.detail is None


@pytest.mark.parametrize("status,code", [(403, client.REFUSED), (413, client.TEXT_TOO_LONG),
                                         (429, client.RATE_LIMITED), (404, client.UNKNOWN_CONVERSATION),
                                         (503, client.NOT_READY)])
def test_a_named_status_keeps_its_code_and_carries_the_providers_reason(monkeypatch, status, code):
    cli, _ = _client(monkeypatch, status, json.dumps({"error": f"reason {status} {TOKEN} " + "x" * 500}).encode())
    with pytest.raises(client.ProviderError) as exc:
        asyncio.run(cli.send("c", "hi", reply_to=None, client_ref="r1"))
    assert exc.value.code == code and exc.value.status == status
    assert exc.value.detail.startswith(f"reason {status}") and len(exc.value.detail) <= client.MAX_DETAIL_CHARS
    assert TOKEN not in exc.value.detail



@pytest.mark.parametrize("answer", [{"message_id": "g1"}, {"message_id": "g1", "status": "weird"},
                                    {"message_id": "g1", "status": 7, "sent_at": "garbage"}])
def test_a_2xx_send_with_a_message_id_and_an_odd_status_is_sent(monkeypatch, answer):
    cli, calls = _client(monkeypatch, 201, json.dumps(answer).encode())
    result = asyncio.run(cli.send("c", "hi", reply_to=None, client_ref="r1"))
    assert result.message_id == "g1" and result.status == "sent" and result.status_ok is False
    assert len(calls) == 1


def test_a_2xx_send_with_no_message_id_retries_with_the_same_key_then_says_it_may_have_gone(monkeypatch):
    cli, calls = _client(monkeypatch, 201, b'{"status": "sent"}')
    with pytest.raises(client.ProviderError) as exc:
        asyncio.run(cli.send("c", "hi", reply_to=None, client_ref="r1"))
    assert exc.value.code == client.BAD_ANSWER and "may have accepted" in exc.value.detail
    assert [h["idempotency-key"] for h in calls] == ["r1", "r1"]


@pytest.mark.parametrize("code,status,shown", [(client.REFUSED, 403, "provider_unreachable"),
                                               (client.TEXT_TOO_LONG, 413, "provider_unreachable"),
                                               (client.REJECTED, 422, client.REJECTED)])
def test_the_probe_and_picker_refusal_carries_the_providers_reason(code, status, shown):
    from src.api import messaging_routes
    exc = messaging_routes._provider_down(client.ProviderError(code, status=status, detail="protected chat"))
    assert exc.status_code == 502
    assert exc.detail == {"code": shown, "status": status, "reason": "protected chat"}
    assert messaging_routes._provider_down(client.ProviderError(client.BAD_ANSWER)).status_code == 422

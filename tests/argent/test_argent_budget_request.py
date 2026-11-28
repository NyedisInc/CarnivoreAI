
from __future__ import annotations

import asyncio
import json
import types
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api.argent import cost as routes
from src.core import resource_push
from src.core.argent import budget_requests, cost_poller, notices, work_items
from src.core.argent.lifecycle import PORT_NAME
from src.core.mcp import argent_tools
from src.core.resource_push import topics
from src.plugins.sdk import ports
from tests.argent.test_argent_budget_hold import SERVER, TOKEN, env  # noqa: F401

FILED = {"id": "br_1", "state": "pending", "requested_micros": 5_000_000, "created_at": "2026-11-23T18:00:00Z"}


class Asker:

    def __init__(self, env: Dict[str, Any]) -> None:
        self.post: Any = (201, FILED)
        self.listing: Any = (200, [])
        self.down = False
        self.calls: List[Any] = []
        env["argent"].handler = self.handler
        work_items._pull.transport, work_items._pull.client = httpx.MockTransport(self.handler), None
        ports.register(PORT_NAME, {"on": True})

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, dict(request.url.params), body, request.headers.get("authorization")))
        if self.down:
            raise httpx.ConnectError("down")
        status, payload = self.post if request.method == "POST" else self.listing
        return httpx.Response(status, json=payload)

    def client(self) -> Any:
        from src.core.argent.client import ArgentClient

        return ArgentClient(SERVER, lambda: TOKEN, transport=httpx.MockTransport(self.handler))


@pytest.fixture
def asker(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    budget_requests._last_read.clear()
    pushed: List[str] = []
    monkeypatch.setattr(resource_push, "notify", lambda topic, *a, **k: pushed.append(topic))
    decided: List[Any] = []
    monkeypatch.setattr(notices, "budget_request_decided", lambda *a: decided.append(a))
    agent = Asker(env)
    agent.pushed, agent.decided, agent.env = pushed, decided, env  # type: ignore[attr-defined]
    yield agent
    budget_requests._last_read.clear()


def ask(**kw: Any) -> Any:
    body = {"item_id": "wi_story1", "amount_micros": 5_000_000, "reason": "  release week  ", **kw}
    return asyncio.run(routes.request_budget(routes.BudgetRequest(**body)))


def login_ok() -> bool:
    return not cost_poller.get_runtime().store.login_expired()


def test_a_201_posts_the_agreed_body_and_is_kept_pending(asker: Any) -> None:
    reply = ask()
    assert reply == {"id": "br_1", "state": "pending", "requested_micros": 5_000_000}
    method, path, _params, body, bearer = asker.calls[0]
    assert (method, path) == ("POST", "/v1/my/cli/budget/requests") and bearer == f"Bearer {TOKEN}"
    assert body == {"requested_micros": 5_000_000, "reason": "release week", "work_item_id": "wi_story1"}, "exactly the agreed fields, the reason trimmed"
    listed = asyncio.run(routes.list_budget_requests())
    assert listed["enabled"] is True and [(r["id"], r["item_id"], r["requested_micros"], r["state"]) for r in listed["requests"]] == [("br_1", "wi_story1", 5_000_000, "pending")]
    assert "release week" not in json.dumps(listed), "the asker's reason is not kept"
    assert topics.ARGENT_BUDGET_REQUESTS in asker.pushed
    assert login_ok()


def test_a_second_ask_on_an_item_with_a_pending_one_is_refused_without_a_call(asker: Any) -> None:
    ask()
    asker.calls.clear()
    with pytest.raises(HTTPException) as refused:
        ask(amount_micros=9_000_000)
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "budget_request_pending" and refused.value.detail["id"] == "br_1"
    assert asker.calls == []


def test_a_409_pending_exists_from_argent_reads_already_asked(asker: Any) -> None:
    asker.post = (409, {"error": "pending_exists", "id": "br_other", "message": "SECRET-RAW-TEXT"})
    with pytest.raises(HTTPException) as refused:
        ask()
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "budget_request_pending" and refused.value.detail["id"] == "br_other"
    assert "SECRET-RAW-TEXT" not in json.dumps(refused.value.detail)
    assert asyncio.run(routes.list_budget_requests())["requests"] == [], "nothing was filed here"


@pytest.mark.parametrize("status,body", [(404, {}), (401, {"error": {"code": "unauthorized"}}), (403, {"error": "SECRET-RAW-TEXT"}), (400, {"error": "SECRET-RAW-TEXT"})])
def test_a_refused_route_is_not_available_yet_and_keeps_the_login(asker: Any, status: int, body: Dict[str, Any]) -> None:
    asker.post = (status, body)
    with pytest.raises(HTTPException) as refused:
        ask()
    assert refused.value.status_code == 501 and refused.value.detail["code"] == "budget_request_unavailable"
    assert "SECRET-RAW-TEXT" not in json.dumps(refused.value.detail)
    assert login_ok() and asyncio.run(routes.list_budget_requests())["requests"] == []


def test_any_other_refusal_has_fixed_words(asker: Any) -> None:
    asker.post = (422, {"error": {"code": "validation", "message": "SECRET-RAW-TEXT"}})
    with pytest.raises(HTTPException) as refused:
        ask()
    assert refused.value.status_code == 422 and refused.value.detail["code"] == "argent_refused" and "SECRET-RAW-TEXT" not in json.dumps(refused.value.detail)


@pytest.mark.parametrize("bad", [{"amount_micros": 0}, {"amount_micros": -5}, {"amount_micros": budget_requests.MAX_REQUEST_MICROS + 1}, {"amount_micros": 1.5},
                                 {"amount_micros": "5"}, {"reason": ""}, {"reason": "   "}, {"reason": "x" * 501}, {"item_id": ""}, {"note": "old field"}])
def test_a_bad_ask_is_refused_before_any_call(asker: Any, bad: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        routes.BudgetRequest(**{"item_id": "wi_story1", "amount_micros": 5_000_000, "reason": "release week", **bad})
    assert asker.calls == []
    assert routes.BudgetRequest(item_id="w", amount_micros=budget_requests.MAX_REQUEST_MICROS, reason="x" * 500).reason == "x" * 500


def test_the_mcp_tool_passes_amount_and_reason(asker: Any) -> None:
    spec = next(s for s in argent_tools.SPECS if s.name == "argent_budget_request")
    assert set(spec.required) == {"item_id", "amount_micros", "reason"} and {"amount_micros", "reason"} <= set(spec.properties)
    assert "note" not in spec.properties
    reply = asyncio.run(argent_tools._budget_request(types.SimpleNamespace(args=dict(spec.example), route=routes.request_budget)))
    assert reply["id"] == "br_1" and asker.calls[0][3] == {"requested_micros": 5_000_000, "reason": "fixture", "work_item_id": "wi_fixture"}


def test_the_poll_moves_a_pending_record_to_approved_and_notifies_once(asker: Any) -> None:
    ask()
    asker.calls.clear()
    asker.pushed.clear()
    asker.listing = (200, [{"id": "br_1", "state": "approved", "requested_micros": 5_000_000, "approved_micros": 4_000_000, "decided_at": "2026-11-23T19:00:00Z"}])
    assert asyncio.run(budget_requests.sync(asker.client(), "ten_1")) == 1
    method, path, params, _body, bearer = asker.calls[0]
    assert (method, path) == ("GET", "/v1/my/cli/budget/requests") and "since" in params and bearer == f"Bearer {TOKEN}"
    rec = asyncio.run(routes.list_budget_requests())["requests"][0]
    assert (rec["state"], rec["approved_micros"]) == ("approved", 4_000_000)
    assert asker.pushed == [topics.ARGENT_BUDGET_REQUESTS]
    assert [(d[0], d[2], d[3]) for d in asker.decided] == [("br_1", "approved", "$4.00")]
    asker.calls.clear()
    assert asyncio.run(budget_requests.sync(asker.client(), "ten_1")) == 0 and asker.calls == [] and len(asker.decided) == 1, "decided records are never read again"


def test_the_poll_moves_a_pending_record_to_denied_with_the_reason_then_expired(asker: Any) -> None:
    ask()
    asker.listing = (200, [{"id": "br_1", "state": "denied", "requested_micros": 5_000_000, "decision_reason": "over plan"}])
    assert asyncio.run(budget_requests.sync(asker.client(), "ten_1")) == 1
    rec = asyncio.run(routes.list_budget_requests())["requests"][0]
    assert (rec["state"], rec["decision_reason"]) == ("denied", "over plan")
    assert asker.decided[0][2:] == ("denied", "$5.00", "over plan")
    ask(item_id="wi_story2")
    asker.listing = (200, [{"id": "br_1", "state": "expired"}])
    assert asyncio.run(budget_requests.sync(asker.client(), "ten_1")) == 0
    FILED["id"] = "br_2"
    try:
        asker.post = (201, {**FILED})
        ask(item_id="wi_story3")
    finally:
        FILED["id"] = "br_1"
    asker.listing = (200, [{"id": "br_2", "state": "expired"}])
    assert asyncio.run(budget_requests.sync(asker.client(), "ten_1")) == 1 and asker.decided[-1][2] == "expired"


def test_nothing_pending_means_no_call(asker: Any) -> None:
    assert asyncio.run(budget_requests.sync(asker.client(), "ten_1")) == 0 and asker.calls == []


def test_the_poll_never_reads_faster_than_the_cadence(asker: Any) -> None:
    ask()
    asker.calls.clear()
    clock = iter([1000.0, 1010.0, 1061.0])
    for expected_calls in (1, 1, 2):
        asyncio.run(budget_requests.sync(asker.client(), "ten_1", min_gap=60.0, clock=lambda: next(clock)))
        assert len(asker.calls) == expected_calls


def test_argent_down_dark_or_refusing_keeps_the_record_pending_and_the_login(asker: Any) -> None:
    ask()
    for state in ("down", (404, {}), (401, {}), (500, {})):
        asker.down, asker.listing = state == "down", ((200, []) if state == "down" else state)
        budget_requests._last_read.clear()
        assert asyncio.run(budget_requests.sync(asker.client(), "ten_1")) == 0
        assert [r["state"] for r in asyncio.run(routes.list_budget_requests())["requests"]] == ["pending"] and login_ok() and asker.decided == []
    asker.down = False
    asker.listing = (200, [{"id": "br_1", "state": "weird"}, {"id": "br_1"}, "junk"])
    budget_requests._last_read.clear()
    assert asyncio.run(budget_requests.sync(asker.client(), "ten_1")) == 0, "an unknown state decides nothing"


def test_the_cost_pass_follows_pending_asks_only_while_the_switch_is_on(asker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    ask()
    asker.calls.clear()

    async def quiet(*_a: Any, **_k: Any) -> float:
        return cost_poller.FAST_SECONDS

    async def no_sessions() -> List[Any]:
        return []

    monkeypatch.setattr(cost_poller, "poll_once", quiet)
    monkeypatch.setattr(cost_poller, "live_sessions", no_sessions)
    real_read = cost_poller.settings_module.read
    monkeypatch.setattr(cost_poller.settings_module, "read", lambda: types.SimpleNamespace(enabled=False))
    assert asyncio.run(cost_poller.pass_once()) == cost_poller.SLOW_SECONDS and asker.calls == [], "switch off: no read"
    monkeypatch.setattr(cost_poller.settings_module, "read", real_read)
    asker.listing = (200, [{"id": "br_1", "state": "approved", "approved_micros": 5_000_000}])

    async def fake_client() -> Any:
        return asker.client(), "ten_1"

    monkeypatch.setattr(work_items, "client_for_call", fake_client)
    assert asyncio.run(cost_poller.pass_once()) == cost_poller.FAST_SECONDS
    assert [c[1] for c in asker.calls] == ["/v1/my/cli/budget/requests"] and len(asker.decided) == 1


def test_the_decided_notice_carries_the_reason_as_a_parameter_never_in_the_title(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: List[Dict[str, Any]] = []
    monkeypatch.setattr(notices.service, "raise_alert", lambda key, **kw: seen.append({"key": key, **kw}))
    notices.budget_request_decided("br_1", "Story", "denied", "$5.00", "<b>over plan</b>")
    notices.budget_request_decided("br_2", "Story", "denied", "$5.00", "")
    notices.budget_request_decided("br_3", "Story", "approved", "$4.00", "")
    notices.budget_request_decided("br_4", "Story", "expired", "$5.00", "")
    assert [(s["key"], s["title_key"], s["detail_key"]) for s in seen] == [
        ("argent.budget.request:br_1", "app_alert.argent.budget_denied.title", "app_alert.argent.budget_denied.detail"),
        ("argent.budget.request:br_2", "app_alert.argent.budget_denied.title", "app_alert.argent.budget_denied.detail_bare"),
        ("argent.budget.request:br_3", "app_alert.argent.budget_approved.title", "app_alert.argent.budget_approved.detail"),
        ("argent.budget.request:br_4", "app_alert.argent.budget_expired.title", "app_alert.argent.budget_expired.detail")]
    assert "over plan" not in json.dumps([s["title_key"] for s in seen]) and seen[0]["params"]["reason"] == "<b>over plan</b>"


def test_the_list_route_is_empty_and_calls_nothing_while_the_switch_is_off(asker: Any) -> None:
    from pathlib import Path

    from src.config import settings as app_settings

    ask()
    asker.calls.clear()
    Path(app_settings.auth_config_file).write_text(json.dumps({"argent": {"serverUrl": SERVER, "enabled": False}}))
    app_settings.drop_auth_config_cache()
    ports.unregister(PORT_NAME)
    assert asyncio.run(routes.list_budget_requests()) == {"enabled": False, "requests": []} and asker.calls == []

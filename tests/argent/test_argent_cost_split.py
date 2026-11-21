
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import httpx
import pytest

from src.api.argent import cost as routes
from src.core.argent import cost_split, cost_poller
from src.core.argent.lifecycle import PORT_NAME
from src.plugins.sdk import ports
from src.models.subagents import SessionSubagents, SubagentInfo
from tests.argent.test_argent_budget_hold import Argent, declare, fixture, poll, sessions, standing, env  # noqa: F401

AGENT_A, AGENT_B = "a1b2c3d4e5f6a7b8", "f9e8d7c6b5a49382"


class SplitArgent(Argent):

    def __init__(self) -> None:
        super().__init__()
        self.sub_calls: List[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/my/cost" and request.url.params.get("by") == "sub_agent":
            if self.mode == "up":
                self.sub_calls.append(request.url.params.get("id", ""))
                return httpx.Response(200, json=fixture("cost_by_sub_agent"))
        return super().handler(request)


def _listing(*_a: Any, **_k: Any) -> SessionSubagents:
    info = SubagentInfo(id=AGENT_A, description="write the poller", status="done", status_reason="end_recorded", meta_shape="ok", transcript_shape="ok")
    return SessionSubagents(state="ok", family="claude", subagents=[info])


@pytest.fixture
def split(env: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:  # noqa: F811
    gateway = SplitArgent()
    env["argent"] = gateway
    gateway.standings.update({"wi_proj1": standing("ok", 1_000_000), "wi_story1": standing("ok", 2_000_000)})
    monkeypatch.setattr(cost_poller, "read_session_subagents", _listing)
    declare("ses_fixture1", "", "wi_story1")
    declare("ses_fixture1", AGENT_B, "wi_proj1")
    cost_split.clear()
    yield env
    cost_split.clear()


def test_the_split_is_asked_only_for_watched_rows_and_named_and_rolled_up(split: Dict[str, Any]) -> None:
    argent = split["argent"]
    poll(split, sessions("ses_fixture1"))
    assert argent.sub_calls == [] and "agents" not in cost_poller.snapshot()["sessions"]["10"], "nobody watches: no by=sub_agent call, no split"
    assert cost_split.watch("w1", ["99"], time.time()) is True
    poll(split, sessions("ses_fixture1"))
    assert argent.sub_calls == [], "a watch for another row asks nothing about this one"

    assert cost_split.watch("w1", ["10"], time.time()) is True and cost_split.watch("w2", ["10"], time.time()) is False
    poll(split, sessions("ses_fixture1"))
    assert argent.sub_calls == ["ses_fixture1"], "keyed on the Argent session id, once per pass"
    agents = cost_poller.snapshot()["sessions"]["10"]["agents"]
    assert [(a["agent_id"], a["name"], a["item_id"], a["cost_micros"]) for a in agents] == [
        ("", None, "wi_story1", 900_000),
        (AGENT_A, "write the poller", "wi_story1", 300_000),
        (AGENT_B, AGENT_B[:8], "wi_proj1", 34_500),
    ], "root first and unnamed, description else short id, each rolled onto its own item else the root's"

    cost_split.watch("w1", [], time.time())
    cost_split.watch("w2", [], time.time())
    poll(split, sessions("ses_fixture1"))
    assert argent.sub_calls == ["ses_fixture1"] and "agents" not in cost_poller.snapshot()["sessions"]["10"], "closed: no more calls and the split is dropped"
    cost_split.watch("w1", ["10"], time.time() - cost_split.WATCH_TTL - 1)
    poll(split, sessions("ses_fixture1"))
    assert argent.sub_calls == ["ses_fixture1"], "an expired registration is not polled"


def test_a_failed_call_keeps_the_last_split_and_unmeasured_is_never_zero(split: Dict[str, Any]) -> None:
    argent = split["argent"]
    cost_split.watch("w1", ["10"], time.time())
    poll(split, sessions("ses_fixture1"))
    first = cost_poller.snapshot()["sessions"]["10"]["agents"]
    for mode in ("down", "dark"):
        argent.mode = mode
        poll(split, sessions("ses_fixture1"))
        assert cost_poller.snapshot()["sessions"]["10"]["agents"] == first, f"{mode}: the last split stays"
    rows = cost_split.rows({"items": [{"id": "", "cost_micros": None}, {"id": "x"}, {"cost_micros": 5}]}, [], {})
    assert [r["cost_micros"] for r in rows or []] == [None, None], "no measurement reads None, a row with no id is dropped"
    assert cost_split.rows({"items": "bad"}, [], {}) is None and cost_split.rows(None, [], {}) is None


def test_the_route_registers_only_with_the_feature_on(split: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    ports.register(PORT_NAME, {"on": True})
    body = routes.AgentWatch(client_id="w1", row_ids=["10"])
    assert asyncio.run(routes.watch_agent_cost(body)) == {"enabled": True, "watching": 1}
    cost_split.clear()
    monkeypatch.setattr(routes, "feature_on", lambda: False)
    assert asyncio.run(routes.watch_agent_cost(body)) == {"enabled": False, "watching": 0}
    assert cost_split.watched_rows(time.time()) == set(), "off: nothing registered, so nothing is polled"

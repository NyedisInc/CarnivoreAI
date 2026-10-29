
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.core.flow_data import mcp_events
from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp_usage import old_names as counter, report, rollup
from src.cplugs.huddle import rules
from src.cplugs.sdk import old_names as sdk
from tests.python.cplugs.huddle.test_task_manager_mcp import CALLER, call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.mcp.test_mcp_usage_counter import world  # noqa: F401

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def counting(world):  # noqa: F811
    counter._pending.clear()
    counter.install()
    yield world
    sdk.install_sink(None)
    counter._pending.clear()


def _counted(world, via=None):
    counter.flush(world.usage)
    return {(n, v): c for _d, _k, n, v, c in world.usage.old_names_between("0000-00-00", "9999-99-99") if via in (None, v)}


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def test_an_old_name_through_the_mcp_update_is_counted_as_a_pane_and_its_tool_name_is_logged(counting, manager):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "later", actor="joe")["id"]
    ok, moved = call(manager, "huddle_update", {"item": item, "state": "back_burner"})
    assert ok and moved["state"] == "todo"
    assert _counted(counting) == {("back_burner", "pane"): 1}
    assert mcp_events.flush(10)
    assert [e["tool"] for e in mcp_events.recent(tool="huddle_update")] == ["huddle_update"]


def test_an_old_name_through_the_http_route_is_counted_as_a_route(counting, client):  # noqa: F811
    item = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "park it"}).json()
    done = client.patch(f"/api/v1/cplugs/huddle/items/{item['id']}", json={"state": "waiting_install"})
    assert done.status_code == 200 and done.json()["state"] == "waiting"
    assert _counted(counting) == {("waiting_install", "route"): 1}


def test_each_old_name_in_a_batch_is_counted_once(counting, manager):  # noqa: F811
    store = huddle_store(manager)
    a, b = (store.add("12", f"item {i}", actor="joe")["id"] for i in range(2))
    ops = [{"op": "update", "item_id": a, "state": "done_by_claude", "review_description": "check it"},
           {"op": "update", "item_id": b, "state": "back_burner"}]
    ok, body = call(manager, "huddle_batch", {"list_id": "mine", "ops": ops})
    assert ok and body["applied"] == 2
    assert _counted(counting) == {("done_by_claude", "pane"): 1, ("back_burner", "pane"): 1}


def test_a_current_name_is_never_counted(counting, manager, client):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "x", actor="joe")["id"]
    for state in ("todo", "waiting", "review", "open"):
        call(manager, "huddle_update", {"item": item, "state": state, "waiting_on": "a reboot", "wait_kind": "event"})
    assert rules.canonical_state("done") == "done" and rules.canonical_state(None) is None
    assert _counted(counting) == {}


def test_building_the_schema_does_not_count(counting):  # noqa: F811
    assert rules.canonical_state("approved", count=False) == "done"
    assert counter.waiting() == {}


def test_the_via_names_a_pane_an_external_token_and_a_peer():
    assert tools._old_name_via(AgentCaller("s", "cloude_a", "s")) == "pane"
    assert tools._old_name_via(AgentCaller("mcp-token:3", "mcp-token:3", "mcp-token:3", "script", "write")) == "external"
    assert tools._old_name_via(AgentCaller("mcp-token:3", "x", "x")) == "external"
    assert tools._old_name_via(AgentCaller("s", "cloude_a", "s", proxied_agent_id=4)) == "peer"
    with sdk.using("peer", "cloude_a"):
        assert sdk._context.get() == ("peer", "cloude_a")
    assert sdk._context.get() == ("route", "")


def test_without_a_sink_nothing_is_counted_and_a_failing_sink_never_fails_the_input(world, manager):  # noqa: F811
    sdk.install_sink(None)
    counter._pending.clear()
    item = huddle_store(manager).add("all", "later", actor="joe")["id"]
    assert call(manager, "huddle_update", {"item": item, "state": "back_burner"})[0]
    assert counter.waiting() == {}

    def broken(kind, name, via, caller):
        raise OSError("disk gone")

    sdk.install_sink(broken)
    try:
        ok, moved = call(manager, "huddle_update", {"item": item, "state": "open"})
        assert ok and moved["state"] == "open"
        assert rules.canonical_state("approved") == "done"
    finally:
        sdk.install_sink(None)


def test_a_failed_flush_keeps_the_counts_for_the_next_pass(counting):  # noqa: F811
    counter.record("state", "approved", "pane")

    class Broken:
        def add_old_names(self, rows):
            raise OSError("read only")

    with pytest.raises(OSError):
        counter.flush(Broken())
    assert sum(counter.waiting().values()) == 1
    assert counter.flush(counting.usage) == 1 and counter.waiting() == {}


def test_two_flushes_add_up_and_the_report_shows_zero_for_an_unused_name(counting):  # noqa: F811
    counter.record("state", "back_burner", "pane", now=NOW)
    counter.record("state", "back_burner", "route", now=NOW)
    rollup.run(NOW, counting.usage)
    counter.record("state", "back_burner", "pane", now=NOW)
    rollup.run(NOW, counting.usage)
    block = {r["name"]: r for r in report.build(30, ["whoami"], counting.usage, NOW)["old_names"]}
    assert set(block) >= set(rules.STATE_ALIASES)
    used = block["back_burner"]
    assert (used["total"], used["calls_7d"], used["by_via"], used["last_used_day"]) == (3, 3, {"pane": 2, "route": 1}, "2026-10-14")
    assert block["approved"]["total"] == 0 and block["approved"]["calls_7d"] == 0 and block["approved"]["last_used_day"] is None


def test_a_use_older_than_a_week_is_in_the_window_but_not_in_the_week(counting):  # noqa: F811
    counting.usage.add_old_names([("2026-10-01", "state", "approved", "pane", 4)])
    row = {r["name"]: r for r in report.build(30, [], counting.usage, NOW)["old_names"]}["approved"]
    assert (row["total"], row["calls_7d"], row["last_used_day"]) == (4, 0, "2026-10-01")


def test_the_mcp_usage_tool_carries_old_names(counting, manager):  # noqa: F811
    item = huddle_store(manager).add("all", "later", actor="joe")["id"]
    assert call(manager, "huddle_update", {"item": item, "state": "back_burner"})[0]
    res = asyncio.run(tools.call_tool(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())), CALLER, "mcp_usage", {"days": 7}))
    assert "isError" not in res, res
    row = {r["name"]: r for r in json.loads(res["content"][0]["text"])["old_names"]}["back_burner"]
    assert row["total"] == 1 and row["by_via"] == {"pane": 1} and row["last_used_day"] == _today()

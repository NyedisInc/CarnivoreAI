
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp_usage import old_names as counter, report, rollup
from src.cplugs.sdk import old_names as sdk
from tests.python.cplugs.huddle.test_task_manager_mcp import CALLER, call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.mcp.test_mcp_usage_counter import world  # noqa: F401

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
GONE = ("state", ["gone_a", "gone_b"])
REMOVED_TASK_MANAGER_NAMES = {"approved", "approved_with_note", "waiting_install", "back_burner", "done_by_claude", "POST /cplugs/huddle/tell",
                              "heldTellMinutes", "tellQuietSeconds", "tellCapSeconds"}


@pytest.fixture()
def declared():
    before = {k: set(v) for k, v in sdk._declared.items()}
    sdk.declare(*GONE)
    yield
    sdk._declared.clear()
    sdk._declared.update(before)


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


def test_a_declared_name_is_counted_as_a_pane_inside_a_tool_call_and_a_route_outside(counting, declared):  # noqa: F811
    with sdk.using("pane", "cloude_a"):
        sdk.note("state", "gone_a")
    sdk.note("state", "gone_a")
    assert _counted(counting) == {("gone_a", "pane"): 1, ("gone_a", "route"): 1}


def test_a_retired_task_manager_state_name_is_refused_and_counted_nowhere(counting, manager, client):  # noqa: F811
    store = huddle_store(manager)
    item = store.add("all", "later", actor="joe")["id"]
    ok, _ = call(manager, "task_manager_update", {"item": item, "state": "back_burner"})
    assert not ok
    made = client.post("/api/v1/cplugs/huddle/lists/12/items", json={"text": "park it"}).json()
    assert 400 <= client.patch(f"/api/v1/cplugs/huddle/items/{made['id']}", json={"state": "waiting_install"}).status_code < 500
    assert _counted(counting) == {}


def test_the_old_tool_name_is_unknown_and_the_report_lists_no_removed_task_manager_name(counting, manager):  # noqa: F811
    assert not tools.has_tool("huddle_update")
    names = {r["name"] for r in report.build(30, [], counting.usage, NOW)["old_names"]}
    assert not names & REMOVED_TASK_MANAGER_NAMES


def test_the_via_names_a_pane_an_external_token_and_a_peer():
    assert tools._old_name_via(AgentCaller("s", "cloude_a", "s")) == "pane"
    assert tools._old_name_via(AgentCaller("mcp-token:3", "mcp-token:3", "mcp-token:3", "script", "write")) == "external"
    assert tools._old_name_via(AgentCaller("mcp-token:3", "x", "x")) == "external"
    assert tools._old_name_via(AgentCaller("s", "cloude_a", "s", proxied_agent_id=4)) == "peer"
    with sdk.using("peer", "cloude_a"):
        assert sdk._context.get() == ("peer", "cloude_a")
    assert sdk._context.get() == ("route", "")


def test_without_a_sink_nothing_is_counted_and_a_failing_sink_never_fails_the_input(world, declared):  # noqa: F811
    sdk.install_sink(None)
    counter._pending.clear()
    sdk.note("state", "gone_a")
    assert counter.waiting() == {}

    def broken(kind, name, via, caller):
        raise OSError("disk gone")

    sdk.install_sink(broken)
    try:
        sdk.note("state", "gone_a")
    finally:
        sdk.install_sink(None)


def test_a_failed_flush_keeps_the_counts_for_the_next_pass(counting):  # noqa: F811
    counter.record("state", "gone_a", "pane")

    class Broken:
        def add_old_names(self, rows):
            raise OSError("read only")

    with pytest.raises(OSError):
        counter.flush(Broken())
    assert sum(counter.waiting().values()) == 1
    assert counter.flush(counting.usage) == 1 and counter.waiting() == {}


def test_two_flushes_add_up_and_the_report_shows_zero_for_an_unused_name(counting, declared):  # noqa: F811
    counter.record("state", "gone_a", "pane", now=NOW)
    counter.record("state", "gone_a", "route", now=NOW)
    rollup.run(NOW, counting.usage)
    counter.record("state", "gone_a", "pane", now=NOW)
    rollup.run(NOW, counting.usage)
    block = {r["name"]: r for r in report.build(30, ["whoami"], counting.usage, NOW)["old_names"]}
    assert set(block) >= set(GONE[1])
    used = block["gone_a"]
    assert (used["total"], used["calls_7d"], used["by_via"], used["last_used_day"]) == (3, 3, {"pane": 2, "route": 1}, "2026-10-14")
    assert block["gone_b"]["total"] == 0 and block["gone_b"]["calls_7d"] == 0 and block["gone_b"]["last_used_day"] is None


def test_a_use_older_than_a_week_is_in_the_window_but_not_in_the_week(counting, declared):  # noqa: F811
    counting.usage.add_old_names([("2026-10-01", "state", "gone_a", "pane", 4)])
    row = {r["name"]: r for r in report.build(30, [], counting.usage, NOW)["old_names"]}["gone_a"]
    assert (row["total"], row["calls_7d"], row["last_used_day"]) == (4, 0, "2026-10-01")


def test_stored_rows_of_a_name_nobody_declares_any_more_are_not_reported(counting):  # noqa: F811
    counting.usage.add_old_names([("2026-10-12", "state", "back_burner", "pane", 5), ("2026-10-12", "route", "POST /cplugs/huddle/tell", "route", 2)])
    names = {r["name"] for r in report.build(30, [], counting.usage, NOW)["old_names"]}
    assert not names & REMOVED_TASK_MANAGER_NAMES


def test_the_mcp_usage_tool_carries_old_names(counting, manager, declared):  # noqa: F811
    sdk.note("state", "gone_a")
    res = asyncio.run(tools.call_tool(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())), CALLER, "mcp_usage", {"days": 7}))
    assert "isError" not in res, res
    row = {r["name"]: r for r in json.loads(res["content"][0]["text"])["old_names"]}["gone_a"]
    assert row["total"] == 1 and row["by_via"] == {"route": 1} and row["last_used_day"] == _today()

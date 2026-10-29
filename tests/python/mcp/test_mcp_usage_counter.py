
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.api import mcp_usage_routes
from src.api.auth import require_auth
from src.config import settings
from src.core.flow_data import mcp_events
from src.core.mcp import pending, token_store, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp_usage import report, rollup, store as usage_store
from src.main import app
from tests.python.mcp.test_mcp_external_tokens import _tool, env  # noqa: F401
from tests.s7_helpers import migrated_connection

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)
VIEW = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
SECRET = "ghp_" + "Zz9Qx7" * 6


def _at(days_ago: int, hour: int = 10) -> float:
    return (NOW.replace(hour=hour, minute=0) - timedelta(days=days_ago)).timestamp()


@pytest.fixture()
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    migrated_connection(state).close()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state)
    usage = usage_store.UsageStore(tmp_path / "mcp_usage.db")
    usage_store.set_store(usage)
    counter = iter(range(10_000))

    def add(tool, kind="pane", outcome="ok", when=None, session=None, call_id=None):
        conn = migrated_connection(state)
        conn.execute("INSERT INTO mcp_events (call_id, started_at, tool, caller_kind, caller_session_id, outcome) VALUES (?,?,?,?,?,?)",
                     (call_id or f"c{next(counter)}", when if when is not None else _at(0), tool, kind, session, outcome))
        conn.commit()
        conn.close()

    yield SimpleNamespace(state=state, usage=usage, add=add)
    usage_store.set_store(None)


def _table(usage):
    return sorted(usage.rows_between("0000-00-00", "9999-99-99"))


def test_the_rollup_counts_each_call_once_per_day_tool_kind_and_outcome(world):
    for _ in range(3):
        world.add("whoami", session="ses_a")
    world.add("whoami", kind="external", outcome="denied")
    world.add("sessions_list", outcome=None)
    world.add("whoami", when=_at(1), session="ses_a")
    world.add("whoami", call_id="dup", session="ses_a")
    world.add("whoami", call_id="dup", session="ses_a")
    rollup.run(NOW, world.usage)
    assert _table(world.usage) == [
        ("2026-10-12", "whoami", "pane", "ok", 1),
        ("2026-10-13", "sessions_list", "pane", "incomplete", 1),
        ("2026-10-13", "whoami", "external", "denied", 1),
        ("2026-10-13", "whoami", "pane", "ok", 4),
    ]


def test_a_parked_writes_internal_rerun_is_not_a_second_call(world):
    world.add("session_notes_put", kind="external", outcome="ok")
    world.add("session_notes_put", kind="pane", session="mcp-token:7")
    world.add("session_notes_put", kind="pane", session="ses_real")
    rollup.run(NOW, world.usage)
    assert _table(world.usage) == [("2026-10-13", "session_notes_put", "external", "ok", 1),
                                   ("2026-10-13", "session_notes_put", "pane", "ok", 1)]


def test_a_rerun_never_double_counts_and_old_days_freeze_after_the_log_prunes(world):
    world.add("whoami", when=_at(5), session="ses_a")
    world.add("whoami", when=_at(0), session="ses_a")
    rollup.run(NOW, world.usage)
    first = _table(world.usage)
    rollup.run(NOW, world.usage)
    assert _table(world.usage) == first
    conn = migrated_connection(world.state)
    conn.execute("DELETE FROM mcp_events WHERE started_at < ?", (_at(2),))
    conn.commit()
    conn.close()
    world.add("whoami", when=_at(0, hour=12), session="ses_a")
    rollup.run(NOW, world.usage)
    assert [r for r in _table(world.usage) if r[0] == "2026-10-08"] == [("2026-10-08", "whoami", "pane", "ok", 1)]
    assert [r for r in _table(world.usage) if r[0] == "2026-10-13"] == [("2026-10-13", "whoami", "pane", "ok", 2)]


def test_an_app_that_was_down_for_days_fills_the_gap_from_the_log(world):
    world.add("whoami", when=_at(9), session="ses_a")
    rollup.run(NOW - timedelta(days=9), world.usage)
    world.add("whoami", when=_at(9, hour=14), session="ses_a")
    world.add("whoami", when=_at(6), session="ses_a")
    rollup.run(NOW, world.usage)
    assert {r[0]: r[4] for r in _table(world.usage)} == {"2026-10-04": 2, "2026-10-07": 1}


def test_a_day_the_log_has_begun_to_prune_is_never_recomputed(world):
    old = (NOW - timedelta(days=45)).date().isoformat()
    world.usage.replace_from("0000-00-00", [(old, "whoami", "pane", "ok", 9)])
    rollup.run(NOW, world.usage)
    assert _table(world.usage) == [(old, "whoami", "pane", "ok", 9)]


def test_the_store_keeps_ninety_days(world):
    world.usage.replace_from("0000-00-00", [("2026-07-01", "whoami", "pane", "ok", 3), ("2026-07-20", "whoami", "pane", "ok", 3)])
    rollup.run(NOW, world.usage)
    assert [r[0] for r in _table(world.usage)] == ["2026-07-20"]


def test_only_counts_are_stored_and_a_secret_argument_leaves_no_trace(world):
    reader = AgentCaller("ext", "ext", "ext", "tok", "read")
    asyncio.run(tools.call_tool(SimpleNamespace(), reader, "session_stop", {"target": "ses_secret_target", "text": SECRET}))
    assert mcp_events.flush(10)
    rollup.run(datetime.now(timezone.utc), world.usage)
    assert _table(world.usage)[0][1:] == ("session_stop", "external", "denied", 1)
    assert [c[1] for c in sqlite3.connect(world.usage.path).execute("PRAGMA table_info(mcp_tool_daily)")] == [
        "day", "tool", "caller_kind", "outcome", "calls"]
    blob = world.usage.path.read_bytes()
    assert SECRET.encode() not in blob and b"ses_secret_target" not in blob


def test_a_parked_external_write_that_the_owner_approves_counts_once(world, env):  # noqa: F811
    client, _mgr, store, _cfg = env
    _, secret = store.mint("script", "write")
    out = json.loads(_tool(client, secret, "session_notes_put", {"target": "cloude_b", "body": "x", "expected_revision": 0})["content"][0]["text"])
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        assert client.post(f"/api/v1/agent-actions/{out['id']}/approve").status_code == 200
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert mcp_events.flush(10)
    logged = [(e["caller_kind"], (e["caller_session_id"] or "")[:10]) for e in mcp_events.recent(tool="session_notes_put")]
    assert sorted(logged) == [("external", ""), ("pane", "mcp-token:")]
    rollup.run(datetime.now(timezone.utc), world.usage)
    assert [(r[2], r[3], r[4]) for r in _table(world.usage) if r[1] == "session_notes_put"] == [("external", "ok", 1)]


def test_the_report_names_every_registered_tool_and_flags_the_retired(world):
    world.add("whoami", session="ses_a")
    world.add("whoami", when=_at(40), session="ses_a")
    world.add("retired_tool", session="ses_a")
    rollup.run(NOW, world.usage)
    world.usage.replace_from("2026-09-03", [r for r in _table(world.usage) if r[0] >= "2026-09-03"] + [("2026-09-03", "sessions_list", "pane", "ok", 2)])
    answer = report.build(30, ["whoami", "sessions_list", "projects_list"], world.usage, NOW)
    assert answer["window"] == {"from": "2026-09-14", "to": "2026-10-13", "days": 30}
    rows = {r["tool"]: r for r in answer["tools"]}
    assert set(rows) == {"whoami", "sessions_list", "projects_list", "retired_tool"}
    assert rows["whoami"]["total"] == 1 and rows["whoami"]["by_caller_kind"] == {"pane": 1} and rows["whoami"]["by_outcome"] == {"ok": 1}
    assert rows["whoami"]["last_called_day"] == "2026-10-13" and rows["whoami"]["registered"] is True
    assert rows["retired_tool"]["registered"] is False and rows["retired_tool"]["total"] == 1
    assert rows["sessions_list"]["total"] == 0 and rows["sessions_list"]["last_called_day"] == "2026-09-03"
    assert rows["projects_list"]["last_called_day"] is None
    assert answer["zero_call_tools"] == ["projects_list", "sessions_list"]


def test_the_route_rolls_up_first_so_a_call_made_now_counts_and_lists_hidden_tools(world):
    caller = AgentCaller("ses_a", "cloude_a", "ses_a")
    asyncio.run(tools.call_tool(SimpleNamespace(), caller, "whoami", {}))
    assert mcp_events.flush(10)
    answer = asyncio.run(mcp_usage_routes.get_mcp_usage(days=7))
    rows = {r["tool"]: r for r in answer["tools"]}
    assert rows["whoami"]["total"] >= 1 and {"flow_get", "notify"} <= set(rows)
    assert set(tools.tool_names()) <= set(rows) and answer["window"]["days"] == 7
    assert "whoami" not in answer["zero_call_tools"]


def test_the_mcp_tool_is_a_read_tool_that_leaves_out_all_zero_rows(world):
    world.add("whoami", session="ses_a", when=datetime.now(timezone.utc).timestamp())
    rollup.run(datetime.now(timezone.utc), world.usage)
    for caller in (AgentCaller("ses_a", "cloude_a", "ses_a"), AgentCaller("x", "x", "x", "tok", "read")):
        assert "mcp_usage" in {d["name"] for d in tools.tool_definitions(caller)}
        res = asyncio.run(tools.call_tool(VIEW, caller, "mcp_usage", {"days": 3}))
        assert "isError" not in res, res
        body = json.loads(res["content"][0]["text"])
        assert "whoami" in {r["tool"] for r in body["tools"]}
        assert all(r["total"] > 0 or not r["registered"] for r in body["tools"]) and "sessions_list" in body["zero_call_tools"]
    assert len(tools._TOOLS["mcp_usage"][0]) < 400
    for bad in ({"days": 0}, {"days": 91}, {"days": "7"}, {"days": True}, {"surplus": 1}):
        assert asyncio.run(tools.call_tool(VIEW, AgentCaller("a", "a", "a"), "mcp_usage", bad))["isError"] is True

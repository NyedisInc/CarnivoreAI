
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.config.mcp import McpConfig
from src.core.mcp import agent_tool_switches, tool_groups, tool_switches, tools
from src.core.mcp.caller import AgentCaller
from tests.python.mcp.test_mcp_endpoint import env  # noqa: F401

pytestmark = pytest.mark.real_agent_tool_switches

PANE = AgentCaller(session_id="ses_a", tmux_name="carnivore_a", current_session_id="ses_a")
TOOL = "sessions_list"


@pytest.fixture
def cfg(monkeypatch):
    block = McpConfig()
    fake = SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=block))
    monkeypatch.setattr(tool_switches, "settings", fake)
    monkeypatch.setattr(agent_tool_switches, "settings", fake)
    return block


def _names(caller=PANE) -> set:
    return {d["name"] for d in tools.tool_definitions(caller)}


def test_every_tool_defaults_on(cfg) -> None:
    assert tool_switches.DEFAULT_OFF <= set(tools.tool_names())
    assert all(tool_switches.is_on(n, {}) or n in tool_switches.DEFAULT_OFF for n in tools.tool_names())
    assert TOOL in _names() and McpConfig().tool_overrides == {}


def test_off_hides_the_tool_and_refuses_the_call_then_on_restores_it(cfg) -> None:
    cfg.tool_overrides = {TOOL: False}
    assert TOOL not in _names()
    result = asyncio.run(tools.call_tool(None, PANE, TOOL, {}))
    assert result["isError"] is True and "is switched off" in result["content"][0]["text"]
    assert TOOL in _names(None)
    cfg.tool_overrides = {TOOL: True}
    assert TOOL in _names()


def test_a_retired_alias_is_refused_in_the_callers_own_word(cfg) -> None:
    from src.core.mcp import aliases

    old, new = next(iter(aliases.table().items()))
    cfg.agent_huddle_tools = True
    cfg.tool_overrides = {new: False}
    text = asyncio.run(tools.call_tool(None, PANE, old, {}))["content"][0]["text"]
    assert text.startswith(f"{old} is switched off")


def test_whoami_cannot_be_switched_off_and_default_off_wins_until_chosen(cfg, monkeypatch) -> None:
    assert tool_switches.is_on("whoami", {"whoami": False})
    monkeypatch.setattr(tool_switches, "DEFAULT_OFF", frozenset({TOOL}))
    assert not tool_switches.is_on(TOOL, {})
    assert tool_switches.is_on(TOOL, {TOOL: True})
    assert tool_switches.merged({TOOL: True}, frozenset({TOOL}), {}) == {TOOL: True}
    assert tool_switches.merged({TOOL: False}, frozenset({TOOL}), {TOOL: True}) == {}


def test_merged_rejects_unknown_and_always_on() -> None:
    with pytest.raises(tool_switches.ToolSwitchError):
        tool_switches.merged({"nope": False}, frozenset({"whoami"}), {})
    with pytest.raises(tool_switches.ToolSwitchError):
        tool_switches.merged({"whoami": False}, frozenset({"whoami"}), {})


def test_a_family_that_is_off_still_hides_a_tool_switched_on(cfg) -> None:
    cfg.tool_overrides = {"task_manager_add": True}
    assert "task_manager_add" not in _names()
    cfg.agent_huddle_tools = True
    assert "task_manager_add" in _names()


def test_family_hidden_says_why_only_while_the_family_is_off(cfg) -> None:
    from src.api import mcp_tool_routes

    def row(name: str) -> dict:
        return next(t for g in mcp_tool_routes.tools_answer()["groups"] for t in g["tools"] if t["name"] == name)

    assert row("swarm_roster")["family_hidden"] is False and row("swarm_roster")["hidden_because"] == ""
    assert row("task_manager_add")["family_hidden"] is True and "huddle" in row("task_manager_add")["hidden_because"]
    cfg.agent_huddle_tools = True
    assert row("task_manager_add")["family_hidden"] is False and row("task_manager_add")["hidden_because"] == ""


def test_a_switch_moves_the_fingerprint(cfg) -> None:
    from src.core.mcp import protocol

    before = protocol.tool_fingerprint(PANE)
    cfg.tool_overrides = {TOOL: False}
    assert protocol.tool_fingerprint(PANE) != before


def test_the_route_needs_the_owner_validates_and_writes_through_the_writer(env, usage, monkeypatch, tmp_path) -> None:  # noqa: F811
    from src.api import mcp_tool_routes
    from src.api.auth import require_auth
    from src.core import config_writer
    from src.main import app

    client, _mgr, _cfg = env
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"mcp": {"channels": true}}')
    fake = SimpleNamespace(auth_config_file=str(cfg_file), drop_auth_config_cache=lambda: None,
                           load_auth_config=lambda: SimpleNamespace(mcp=McpConfig(**json.loads(cfg_file.read_text())["mcp"])))
    for module in (mcp_tool_routes, tool_switches, agent_tool_switches):
        monkeypatch.setattr(module, "settings", fake)
    commits: list = []
    real = config_writer.commit
    monkeypatch.setattr(config_writer, "commit", lambda path, mutate: commits.append(path) or real(path, mutate))
    assert client.get("/api/v1/mcp-admin/tools").status_code == 401
    assert client.put("/api/v1/mcp-admin/tools", json={"set": {TOOL: False}}).status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        doc = client.get("/api/v1/mcp-admin/tools").json()
        rows = {t["name"]: t for g in doc["groups"] for t in g["tools"]}
        assert rows[TOOL]["enabled"] is True and rows[TOOL]["default_enabled"] is True and rows["whoami"]["enabled"]
        r = client.put("/api/v1/mcp-admin/tools", json={"set": {TOOL: False}})
        assert r.status_code == 200
        assert {t["name"]: t for g in r.json()["groups"] for t in g["tools"]}[TOOL]["enabled"] is False
        assert json.loads(cfg_file.read_text())["mcp"] == {"channels": True, "tool_overrides": {TOOL: False}}
        assert client.put("/api/v1/mcp-admin/tools", json={"set": {"nope": False}}).status_code == 422
        assert client.put("/api/v1/mcp-admin/tools", json={"set": {"whoami": False}}).status_code == 422
        assert client.put("/api/v1/mcp-admin/tools", json={"set": {TOOL: "no"}}).status_code in (400, 422)
        assert client.put("/api/v1/mcp-admin/tools", json={"set": {}}).status_code in (400, 422)
        client.put("/api/v1/mcp-admin/tools", json={"set": {TOOL: True}})
        assert json.loads(cfg_file.read_text())["mcp"] == {"channels": True, "tool_overrides": {}}
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert len(commits) == 2


@pytest.fixture
def usage(monkeypatch, tmp_path):
    from src.api import mcp_tool_routes
    from src.core.mcp_usage import store as usage_store

    store = usage_store.UsageStore(tmp_path / "mcp_usage.db")
    usage_store.set_store(store)
    monkeypatch.setattr(mcp_tool_routes.rollup, "run", lambda *a, **k: 0)
    yield store
    usage_store.set_store(None)


def _rows(doc: dict) -> dict:
    return {t["name"]: t for g in doc["groups"] for t in g["tools"]}


def test_counts_come_from_the_usage_store_and_a_reset_zeroes_the_view_only(usage) -> None:
    from datetime import datetime, timezone

    from src.core.mcp_usage import view

    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    usage.replace_from("2026-10-13", [("2026-10-13", TOOL, "pane", "ok", 2), ("2026-10-15", TOOL, "pane", "ok", 3)])
    usage.add_old_names([("2026-10-15", "state", "back_burner", "pane", 4)])
    before = view.counts([TOOL], now, usage)
    assert before["since"] is None and before["tools"][TOOL]["calls"] == 5 and before["tools"][TOOL]["daily"][-3:] == [2, 0, 3]
    view.reset([TOOL], now, usage)
    assert view.counts([TOOL], now, usage)["tools"][TOOL] == {"calls": 0, "daily": [0] * 7}
    usage.replace_from("2026-10-15", [("2026-10-15", TOOL, "pane", "ok", 5)])
    after = view.counts([TOOL], now, usage)
    assert after["tools"][TOOL]["calls"] == 2 and after["tools"][TOOL]["daily"][-1] == 2 and after["since"].startswith("2026-10-15T12:00")
    assert sum(r[4] for r in usage.rows_between("2026-10-13", "2026-10-15")) == 7
    assert usage.old_names_between("2026-10-15", "2026-10-15") == [("2026-10-15", "state", "back_burner", "pane", 4)]


def test_the_reset_route_needs_the_owner_and_zeroes_what_the_tab_shows(env, usage, monkeypatch, tmp_path) -> None:  # noqa: F811
    from datetime import datetime, timezone

    from src.api.auth import require_auth
    from src.main import app

    client, _mgr, _cfg = env
    today = datetime.now(timezone.utc).date().isoformat()
    usage.replace_from(today, [(today, TOOL, "pane", "ok", 3)])
    usage.add_old_names([(today, "state", "back_burner", "pane", 4)])
    assert client.post("/api/v1/mcp-admin/tools/usage/reset").status_code == 401
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        got = client.get("/api/v1/mcp-admin/tools").json()
        assert _rows(got)[TOOL]["calls"] == 3 and len(_rows(got)[TOOL]["daily"]) == 7 and got["usage"]["since"] is None
        done = client.post("/api/v1/mcp-admin/tools/usage/reset")
        assert done.status_code == 200 and done.json()["usage"]["since"] and _rows(done.json())[TOOL]["calls"] == 0
        assert _rows(client.get("/api/v1/mcp-admin/tools").json())[TOOL]["calls"] == 0
    finally:
        app.dependency_overrides.pop(require_auth, None)
    assert usage.old_names_between(today, today) == [(today, "state", "back_burner", "pane", 4)]
    assert usage.rows_between(today, today) == [(today, TOOL, "pane", "ok", 3)]


def test_an_unreadable_usage_file_still_lists_the_switches(env, monkeypatch) -> None:  # noqa: F811
    import sqlite3

    from src.api import mcp_tool_routes
    from src.api.auth import require_auth
    from src.main import app

    def boom(*a, **k):
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(mcp_tool_routes.rollup, "run", boom)
    client, _mgr, _cfg = env
    app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    try:
        doc = client.get("/api/v1/mcp-admin/tools").json()
        assert doc["usage"] is None and _rows(doc)[TOOL]["calls"] is None and _rows(doc)[TOOL]["enabled"] is True
        assert client.post("/api/v1/mcp-admin/tools/usage/reset").status_code == 503
    finally:
        app.dependency_overrides.pop(require_auth, None)

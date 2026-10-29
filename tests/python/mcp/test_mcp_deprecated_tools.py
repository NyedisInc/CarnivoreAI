
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.api import mcp_tool_routes
from src.config.mcp import McpConfig
from src.core.mcp import agent_tool_switches, deprecated_tools, tool_groups, tool_switches, tools
from src.core.mcp.caller import AgentCaller

pytestmark = pytest.mark.real_deprecated_default_off

PANE = AgentCaller(session_id="ses_a", tmux_name="carnivore_a", current_session_id="ses_a")
OLD = "session_rename"
LIVE = "sessions_list"


@pytest.fixture
def cfg(monkeypatch):
    block = McpConfig()
    fake = SimpleNamespace(load_auth_config=lambda: SimpleNamespace(mcp=block))
    monkeypatch.setattr(tool_switches, "settings", fake)
    monkeypatch.setattr(agent_tool_switches, "settings", fake)
    return block


def _listed(caller=PANE) -> set:
    return {d["name"] for d in tools.tool_definitions(caller)}


def test_a_deprecated_tool_is_off_by_default_absent_for_an_agent_and_back_when_switched_on(cfg) -> None:
    assert OLD in deprecated_tools.DEPRECATED and OLD in tools.tool_names()
    assert not tool_switches.is_on(OLD, {}) and tool_switches.is_on(LIVE, {})
    assert OLD not in _listed() and OLD in _listed(None)
    cfg.tool_overrides = {OLD: True}
    assert OLD in _listed() and tool_switches.hidden_reason(PANE, OLD) == ""
    cfg.tool_overrides = {}
    assert "is switched off" in tool_switches.hidden_reason(PANE, OLD)


def test_the_stored_choice_persists_like_any_tools_and_default_drops_it() -> None:
    names = frozenset(tools.tool_names())
    on = tool_switches.merged({OLD: True}, names, {})
    assert on == {OLD: True}
    assert tool_switches.merged({OLD: False}, names, on) == {}


def test_every_deprecated_tool_is_registered_off_and_none_is_a_live_tool_in_disguise() -> None:
    registered = set(tools.tool_names())
    assert len(deprecated_tools.DEPRECATED) == 108 and deprecated_tools.DEPRECATED <= registered
    assert tool_switches.DEFAULT_OFF == deprecated_tools.DEPRECATED
    assert "session_delete" not in deprecated_tools.DEPRECATED and tool_switches.is_on("session_delete", {})
    assert not any(tool_switches.is_on(n, {}) for n in deprecated_tools.DEPRECATED)


def test_the_tab_answer_groups_them_last_under_deprecated_and_no_live_group_changes(cfg) -> None:
    doc = mcp_tool_routes.tools_answer()
    names = [g["group"] for g in doc["groups"]]
    assert names[-1] == deprecated_tools.GROUP and names.count(deprecated_tools.GROUP) == 1
    by_group = {g["group"]: {t["name"] for t in g["tools"]} for g in doc["groups"]}
    assert by_group[deprecated_tools.GROUP] == set(deprecated_tools.DEPRECATED)
    rows = {t["name"]: t for g in doc["groups"] for t in g["tools"]}
    assert rows[OLD]["enabled"] is False and rows[OLD]["default_enabled"] is False
    assert rows[LIVE]["enabled"] is True and LIVE not in by_group[deprecated_tools.GROUP]
    live = [n for n in tools.tool_names() if n not in deprecated_tools.DEPRECATED]
    assert tool_groups.group_map(live) == {n: g for n, g in tool_groups.group_map(tools.tool_names()).items() if n in live}


from __future__ import annotations

import asyncio
import re
from typing import Any, Iterator

import pytest

from src.core.mcp import agent_tool_switches, beast_mode, protocol, tools
from src.core.mcp.approvals import call_context, display
from src.core.mcp.caller import AgentCaller
from src.core.swarm import definition, guard

REMOVED = (
    "ai_chat", "ai_decide", "ai_embed", "agent_fork", "crosstalk_watch",
    "swarm_alert", "auto_sleep_settings", "session_keep_awake", "project_company_set", "swarm_set_color",
    "automation_schedule_preview", "ai_presets_list", "company_hue_set",
    "task_manager_delete", "huddle_delete",
)

UNREGISTERED_ON_PURPOSE = {
    "tools.GATED_TOOLS": {"agent_fork": "crosstalk/fork/engine.py still parks and reads Beast Mode under this action name"},
    "call_context.GATED_TOOLS": {"agent_fork": "same engine: a park call site must name a gated action (test_every_park_site_names_a_gated_tool)"},
    "beast_mode.AGENT_ACTIONS": {"agent_fork": "the owner's /sessions/{id}/fork-to route reads approval_skip('agent_fork') for its Beast flags"},
}

_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


def _family_names() -> Iterator[tuple[str, set]]:
    for attr, value in vars(agent_tool_switches).items():
        if attr.startswith("_") or not attr.isupper():
            continue
        groups = value.values() if isinstance(value, dict) else [value]
        for group in groups:
            if isinstance(group, (set, frozenset, tuple, list)) and group and all(isinstance(x, str) for x in group):
                names = {x for x in group if _NAME.match(x)}
                if len(names) == len(group):
                    yield f"agent_tool_switches.{attr}", names


def _name_keyed_sets() -> dict[str, set]:
    sets: dict[str, set] = {
        "tools.WRITE_TOOLS": set(tools.WRITE_TOOLS),
        "tools.BEAST_SCOPE_TOOLS": set(tools.BEAST_SCOPE_TOOLS),
        "tools._UNGATED_WRITES": set(tools._UNGATED_WRITES),
        "tools._TARGETED_WRITES": set(tools._TARGETED_WRITES),
        "tools.GATED_TOOLS": set(tools.GATED_TOOLS),
        "call_context.GATED_TOOLS": set(call_context.GATED_TOOLS),
        "call_context.ACTION_TOOLS (tools)": set(call_context.ACTION_TOOLS.values()),
        "beast_mode.AGENT_ACTIONS": set(beast_mode.AGENT_ACTIONS),
        "beast_mode.ALWAYS_WAITS": set(beast_mode.ALWAYS_WAITS),
        "display._RULES": set(display._RULES),
        "guard.DATA_SAFE": set(guard.DATA_SAFE),
        "definition.CREATE_TOOLS": {t.removeprefix("mcp__carnivore__") for t in definition.CREATE_TOOLS},
    }
    for label, names in _family_names():
        sets[label] = names
    return sets


def test_none_of_the_removed_tools_is_registered_or_listed() -> None:
    listed = {d["name"] for d in tools.tool_definitions()}
    listed_for_a_pane = {d["name"] for d in tools.tool_definitions(AgentCaller("ses_a", "cloude_a", "ses_a"))}
    for name in REMOVED:
        assert name not in tools._TOOLS, name
        assert name not in listed and name not in listed_for_a_pane, name
        assert not tools.has_tool(name), name


@pytest.mark.parametrize("name", REMOVED)
def test_calling_a_removed_tool_is_refused_as_unknown(name: str) -> None:
    caller = AgentCaller("ses_a", "cloude_a", "ses_a")
    message: Any = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": {}}}
    answer = asyncio.run(protocol.handle_message(message, None, caller))
    assert answer["error"]["code"] == protocol.INVALID_PARAMS and "unknown tool" in answer["error"]["message"]
    assert "result" not in answer


def test_every_name_in_every_name_keyed_set_is_a_registered_tool() -> None:
    registered = set(tools._TOOLS)
    sets = _name_keyed_sets()
    assert all(sets.values()), [label for label, names in sets.items() if not names]
    stray: dict[str, list[str]] = {}
    for label, names in sets.items():
        left = names - registered - set(UNREGISTERED_ON_PURPOSE.get(label, {}))
        if left:
            stray[label] = sorted(left)
    assert stray == {}
    for label, allowed in UNREGISTERED_ON_PURPOSE.items():
        assert set(allowed) <= sets[label], f"{label} no longer holds {sorted(set(allowed) - sets[label])}: drop it from the allowlist"
        assert not set(allowed) & registered
    for names in sets.values():
        assert not names & (set(REMOVED) - {"agent_fork"})

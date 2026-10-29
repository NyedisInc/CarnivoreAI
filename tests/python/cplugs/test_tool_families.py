
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from src.core.mcp import tool_families
from src.core.mcp.agent_tool_switches import AgentToolSwitches, hidden_reason
from src.core.mcp.caller import AgentCaller
from src.core.pack.span import proxy_client
from src.core.swarm import definition
from src.cplugs.host import runtime
from src.cplugs.sdk import CplugDefinition, ManifestError, ToolSpec, tool_result
from src.cplugs.sdk.manifest import parse_manifest
from src.cplugs.sdk.tool_families import TASK_MANAGER_PREFIX, TOOL_FAMILIES, family_prefix

PANE = AgentCaller(session_id="ses_a", tmux_name="carnivore_a", current_session_id="ses_a")
TOOL = "task_manager_boards_list"


def _raw(cplug_id: str, tools: list, family: Any = "task_manager") -> Dict[str, Any]:
    raw = {"schema": 1, "id": cplug_id, "name_key": f"cplug.{cplug_id}.name", "description_key": f"cplug.{cplug_id}.description",
           "version": "1.0.0", "icon": "plug", "author": "Joe (ccsliinc)", "min_app_version": "1.0.0", "tier": "builtin",
           "default_enabled": False, "surfaces": {"mcp_tools": tools}}
    if family is not None:
        raw["tool_family"] = family
    return raw


async def _handler(_ctx: Any, _caller: Any, _args: dict) -> dict:
    return tool_result({})


def _definition(cplug_id: str, tools: list) -> CplugDefinition:
    spec = ToolSpec(description="x", properties={}, required=(), handler=_handler)
    return CplugDefinition(manifest=parse_manifest(_raw(cplug_id, tools)), tools={t: spec for t in tools})


def test_the_family_table_is_the_one_source_of_the_prefix() -> None:
    assert TOOL_FAMILIES == {"task_manager": ("huddle", "reviewboard", "tmdevtools"), "widget_lab": ("devwidgetlab",)}
    assert family_prefix("task_manager") == TASK_MANAGER_PREFIX == "task_manager_"
    with pytest.raises(KeyError):
        family_prefix("nothing")


def test_a_granted_plugin_may_name_family_tools_and_its_own() -> None:
    manifest = parse_manifest(_raw("reviewboard", [TOOL, "reviewboard_scan"]))
    assert manifest.tool_family == "task_manager" and manifest.surfaces.mcp_tools == (TOOL, "reviewboard_scan")
    assert parse_manifest(_raw("huddle", ["huddle_list"], family=None)).tool_family == ""


@pytest.mark.parametrize("cplug_id, tools, family, message", [
    ("flow", ["task_manager_x"], "task_manager", "not granted to flow"),
    ("reviewboard", ["task_manager_x"], "taskmanager", "tool_family must be one of"),
    ("reviewboard", ["task_manager_x"], None, "needs tool_family task_manager granted to reviewboard"),
    ("reviewboard", ["task_manager_"], "task_manager", "must be named"),
    ("reviewboard", ["swarm_x"], "task_manager", "must be named reviewboard_<verb> or task_manager_<verb>"),
    ("task", ["task_manager_board_create"], None, "needs tool_family task_manager granted to task"),
])
def test_the_manifest_refuses_a_family_it_was_not_granted(cplug_id: str, tools: list, family: Any, message: str) -> None:
    with pytest.raises(ManifestError, match=message):
        parse_manifest(_raw(cplug_id, tools, family))


def test_two_plugins_never_declare_one_tool_name() -> None:
    runtime.check_definitions((_definition("huddle", ["task_manager_a"]), _definition("reviewboard", ["task_manager_b"])))
    with pytest.raises(runtime.RegistryError, match="already declared by huddle"):
        runtime.check_definitions((_definition("huddle", [TOOL]), _definition("reviewboard", [TOOL])))


def test_a_remote_body_runs_a_task_manager_tool_at_its_home() -> None:
    assert proxy_client.is_proxied(TOOL) and proxy_client.is_proxied("huddle_list")
    assert not proxy_client.is_proxied("task_managerx_list") and not proxy_client.is_proxied("sessions_list")


def test_the_agent_huddle_switch_hides_a_task_manager_tool() -> None:
    off = AgentToolSwitches(huddle=False, swarm=True)
    assert "huddle tools off" in hidden_reason(PANE, TOOL, off)
    assert hidden_reason(PANE, TOOL, AgentToolSwitches(huddle=True, swarm=False)) == ""
    assert hidden_reason(None, TOOL, off) == ""
    assert TASK_MANAGER_PREFIX in tool_families.BY_KEY["huddle"].prefixes


@pytest.mark.parametrize("rank", ["company", "alpha"])
def test_company_and_sysop_are_denied_the_create_type_task_manager_tools(rank: str) -> None:
    deny = json.loads(definition.render_settings(Path("/m"), rank))["permissions"]["deny"]
    assert {"mcp__carnivore__task_manager_board_create", "mcp__carnivore__task_manager_board_revision_add"} <= set(deny)
    project = json.loads(definition.render_settings(Path("/m"), "project"))["permissions"]["deny"]
    assert not any(name.startswith("mcp__carnivore__task_manager_") for name in project)

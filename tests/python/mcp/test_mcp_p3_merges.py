
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.api import computers_routes, descriptions_routes, pack_machines_routes
from src.core.mcp import aliases, deprecated_tools, merged_tools, tool_switches, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.registry import index

pytestmark = pytest.mark.real_deprecated_default_off

PANE = AgentCaller("ses_a", "carnivore_a", "ses_a")
MANAGER = SimpleNamespace(app=SimpleNamespace())


@pytest.fixture(autouse=True)
def stub_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def roster(_request, **kwargs):
        return {"route": "roster", **kwargs}

    async def machines(_request, agents=False):
        return {"route": "machines", "agents": agents}

    async def computers(_request):
        return {"route": "computers"}

    monkeypatch.setattr(descriptions_routes, "get_roster", roster)
    monkeypatch.setattr(pack_machines_routes, "get_machines", machines)
    monkeypatch.setattr(computers_routes, "get_computers", computers)


def _call(name: str, args: dict) -> dict:
    result = asyncio.run(tools.call_tool(MANAGER, PANE, name, args))
    text = result["content"][0]["text"]
    return {"error": text} if result.get("isError") else json.loads(text)


def test_merged_tools_answer_through_the_old_and_the_new_name() -> None:
    roster = _call("agents_lookup", {"view": "roster", "scope": "around"})
    assert roster["route"] == "roster" and roster["scope"] == "around"
    assert _call("sessions_roster", {"scope": "around"}) == roster and _call("agents_lookup", {"scope": "around"}) == roster
    assert _call("sessions_roster", {})["scope"] == "online"
    assert "belong to view" in _call("agents_lookup", {"view": "roster", "query": "x"})["error"]
    assert "belong to view" in _call("agents_lookup", {"view": "agents", "scope": "all"})["error"] and "view must be" in _call("agents_lookup", {"view": "x"})["error"]

    specs = _call("computers_list", {"detail": "specs"})
    assert specs == {"route": "machines", "agents": False} == _call("pack_machines_list", {})
    assert _call("pack_machines_list", {"agents": True})["agents"] is True
    assert _call("computers_list", {}) == {"route": "computers"} == _call("computers_list", {"detail": "link"})
    assert "detail must be" in _call("computers_list", {"detail": "x"})["error"] and "agents goes with" in _call("computers_list", {"agents": True})["error"]


def test_merged_names_are_aliases_with_no_registry_record_of_their_own() -> None:
    for old, merge in merged_tools.MERGED.items():
        assert aliases.is_alias(old) and aliases.canonical(old) == merge.into and aliases.table()[old] == merge.into
        assert old not in index.entries() and merge.into in index.entries()
        assert aliases.capability_id(old) == aliases.capability_id(merge.into) and aliases.flat_name(old) == merge.into
        row, survivor = tools._TOOLS[old], tools._TOOLS[merge.into]
        assert row[1] is survivor[1] and row[3] is survivor[3] and merge.into in row[0] and "OLD NAME" in row[0]
        assert {d["name"] for d in tools.tool_definitions(PANE)} >= {merge.into}
    assert merged_tools.with_preset("sessions_roster", {"view": "agents"}) == {"view": "agents"}
    assert merged_tools.with_preset("agents_lookup", None) == {}


def test_task_manager_delete_is_off_mcp_and_huddle_focus_is_retired_not_deleted() -> None:
    listed = {d["name"] for d in tools.tool_definitions()}
    assert not {"task_manager_delete", "huddle_delete"} & (listed | set(tools.tool_names()) | set(aliases.table()))
    assert "huddle_focus" in tools.tool_names() and "huddle_focus" in deprecated_tools.DEPRECATED
    assert not tool_switches.is_on("huddle_focus", {}) and tool_switches.is_on("huddle_focus", {"huddle_focus": True})
    assert index.entries()["huddle_focus"].id == "task_manager.tasks.focus"

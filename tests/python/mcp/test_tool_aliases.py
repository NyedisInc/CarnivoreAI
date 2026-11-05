
from __future__ import annotations

import asyncio

import pytest

from src.core.mcp import aliases, merged_tools, protocol, tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.host import mcp as cplug_mcp, runtime
from src.cplugs.huddle import CPLUG, mcp as task_manager_mcp
from src.cplugs.sdk.manifest import ManifestError, parse_manifest
from tests.python.cplugs.huddle.test_task_manager_mcp import call, manager  # noqa: F401

REMOVED = {
    "huddle_guide": "task_manager_guide", "huddle_list": "task_manager_tasks_list", "huddle_changes": "task_manager_changes",
    "huddle_schedules_list": "task_manager_schedules_list", "huddle_add": "task_manager_add", "huddle_update": "task_manager_update",
    "huddle_item_state_request": "task_manager_state_request", "huddle_ask": "task_manager_ask", "huddle_reply": "task_manager_reply",
    "huddle_move": "task_manager_move", "huddle_role_set": "task_manager_role_set", "huddle_lead_set": "task_manager_lead_set",
    "huddle_leads_list": "task_manager_leads_list", "huddle_leads_update": "task_manager_leads_update",
    "huddle_group_create": "task_manager_group_create", "huddle_group_update": "task_manager_group_update",
    "huddle_mark_answered": "task_manager_answered_set", "huddle_fork": "task_manager_fork",
    "huddle_batch": "task_manager_batch_run", "huddle_artifact": "task_manager_artifact_add", "huddle_inbox_list": "task_manager_entries_list",
    "huddle_inbox_file": "task_manager_entry_import", "huddle_progress": "task_manager_progress_set", "huddle_wait_update": "task_manager_wait_update",
}
GONE = sorted([*REMOVED, "huddle_focus", "huddle_delete"])


def test_the_alias_table_holds_only_the_merged_tools_now():
    assert aliases.table() == {old: m.into for old, m in merged_tools.MERGED.items()}
    assert dict(CPLUG.manifest.mcp_tool_aliases) == {}
    assert not any(name.startswith("huddle_") for name in aliases.table())


@pytest.mark.parametrize("old,new", sorted(REMOVED.items()))
def test_an_old_name_is_not_registered_or_listed_and_its_new_name_is(old, new):
    listed = {d["name"] for d in tools.tool_definitions()}
    assert old not in tools._TOOLS and old not in listed and not aliases.is_alias(old)
    assert cplug_mcp.spec_of(old) is None
    assert new in tools._TOOLS and new in listed and cplug_mcp.spec_of(new) is not None
    assert old not in tools.WRITE_TOOLS and old not in cplug_mcp.INBOX_TOOLS and old not in cplug_mcp._OWNERS


def test_no_tool_named_huddle_is_registered_anywhere():
    assert [n for n in tools._TOOLS if n.startswith("huddle_")] == []
    assert [n for n in runtime.find("huddle").tools if n.startswith("huddle_")] == []
    assert [n for n in CPLUG.manifest.surfaces.mcp_tools if n.startswith("huddle_")] == []
    assert "huddle_focus" not in task_manager_mcp.TOOLS and not hasattr(task_manager_mcp, "huddle_focus")


@pytest.mark.parametrize("old", GONE)
def test_a_call_to_an_old_name_is_an_unknown_tool(manager, old):  # noqa: F811
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": old, "arguments": {"list": "all"}}}
    answer = asyncio.run(protocol.handle_message(msg, manager, AgentCaller("ses_1", "cloude_a", "ses_1")))
    assert not tools.has_tool(old) and "error" in answer and "unknown tool" in answer["error"]["message"], (old, answer)


def test_a_read_token_sees_the_task_manager_read_and_not_its_writes():
    reader = AgentCaller("tok", "tok", "tok", "tok", "read")
    names = {d["name"] for d in tools.tool_definitions(reader)}
    assert "task_manager_tasks_list" in names
    assert not names & {"task_manager_add", "task_manager_update"}
    assert not tools.allowed(reader, "task_manager_add")


def _raw(**over):
    raw = {"schema": 1, "id": "demo", "name_key": "cplug.demo.name", "description_key": "cplug.demo.description", "version": "1.0.0",
           "icon": "chat", "author": "x", "min_app_version": "1.0.0", "tier": "builtin", "permissions": {"app": []},
           "surfaces": {"mcp_tools": ["demo_things_list"]}}
    raw.update(over)
    return raw


def test_a_manifest_alias_must_name_a_listed_tool_with_the_plugins_prefix():
    assert parse_manifest(_raw(mcp_tool_aliases={"demo_list": "demo_things_list"})).mcp_tool_aliases == {"demo_list": "demo_things_list"}
    for bad in ({"demo_list": "demo_missing_list"},
                {"other_list": "demo_things_list"},
                {"demo_things_list": "demo_things_list"},
                {"demo_a": "demo_things_list", "demo_b": "demo_things_list"},
                ["demo_list"]):
        with pytest.raises(ManifestError):
            parse_manifest(_raw(mcp_tool_aliases=bad))

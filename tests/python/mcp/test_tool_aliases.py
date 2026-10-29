
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from src.core.flow_data import mcp_events
from src.core.mcp import aliases, pending, tools
from src.core.mcp.approvals import runtime as approval_runtime
from src.core.mcp.caller import AgentCaller
from src.core.mcp_usage import rollup
from src.cplugs.host import mcp as cplug_mcp, runtime
from src.cplugs.huddle import mcp as task_manager_mcp, rules
from src.cplugs.sdk.manifest import ManifestError, parse_manifest
from tests.python.cplugs.huddle.test_task_manager_mcp import CALLER, call, huddle_store, manager  # noqa: F401
from tests.python.cplugs.test_cplug_mcp_generic import set_state
from tests.python.mcp.test_mcp_usage_counter import world  # noqa: F401

PLAN = {
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
RETIRED_STATES = ("waiting_install", "back_burner", "done_by_claude")


def test_the_alias_table_is_the_plans_table_and_focus_keeps_its_name():
    from src.core.mcp import merged_tools

    assert aliases.table() == {**PLAN, **{old: m.into for old, m in merged_tools.MERGED.items()}}
    assert "huddle_delete" not in aliases.table() and "task_manager_delete" not in tools._TOOLS
    assert "huddle_focus" in tools._TOOLS and not aliases.is_alias("huddle_focus") and "task_manager_focus" not in tools._TOOLS


@pytest.mark.parametrize("old,new", sorted(PLAN.items()))
def test_an_old_name_and_its_new_name_are_one_toolspec_not_a_copy(old, new):
    assert cplug_mcp.spec_of(old) is not None and cplug_mcp.spec_of(old) is cplug_mcp.spec_of(new)
    assert cplug_mcp.spec_of(new) is task_manager_mcp.TOOLS[new] or cplug_mcp.spec_of(new) is runtime.find("huddle").tools[new]
    assert old not in runtime.find("huddle").tools
    old_row, new_row = tools._TOOLS[old], tools._TOOLS[new]
    assert old_row[1] is new_row[1] and old_row[2] is new_row[2] and old_row[3] is new_row[3]
    assert new in old_row[0] and "old name" in old_row[0].lower()


def test_both_names_are_listed_and_take_the_same_arguments():
    listed = {d["name"]: d for d in tools.tool_definitions()}
    for old, new in PLAN.items():
        assert old in listed and new in listed, (old, new)
        assert listed[old]["inputSchema"] == listed[new]["inputSchema"], (old, new)
    assert "huddle_focus" in listed


def test_a_read_token_sees_neither_spelling_of_a_write_and_both_of_a_read():
    reader = AgentCaller("tok", "tok", "tok", "tok", "read")
    names = {d["name"] for d in tools.tool_definitions(reader)}
    assert {"task_manager_tasks_list", "huddle_list"} <= names
    assert not names & {"task_manager_add", "huddle_add", "task_manager_update", "huddle_update"}
    assert not tools.allowed(reader, "huddle_add") and not tools.allowed(reader, "task_manager_add")


def test_every_set_a_call_is_keyed_by_holds_current_names_only():
    retired = set(aliases.table())
    assert not retired & set(cplug_mcp.BODY_LIMITS) and not retired & set(cplug_mcp.PANE_ONLY_ARGS)
    assert "task_manager_reply" in cplug_mcp.PANE_ONLY_ARGS and "task_manager_board_attachment_add" in cplug_mcp.BODY_LIMITS
    assert {"huddle_add", "task_manager_add"} <= tools.WRITE_TOOLS and {"huddle_list", "task_manager_tasks_list"}.isdisjoint(tools.WRITE_TOOLS)


def test_the_schemas_advertise_only_current_states_and_the_update_still_accepts_a_retired_one(manager):  # noqa: F811
    for name in ("task_manager_update", "huddle_update", "task_manager_add", "huddle_add", "task_manager_fork", "huddle_fork"):
        listed = next(d for d in tools.tool_definitions() if d["name"] == name)["inputSchema"]["properties"]
        enums = [listed[f]["enum"] for f in ("state", "fork_state", "parent_state") if f in listed]
        assert enums and not set(RETIRED_STATES) & {s for enum in enums for s in enum}, name
    store = huddle_store(manager)
    for tool in ("task_manager_update", "huddle_update"):
        for retired, current in (("back_burner", rules.TODO), ("done_by_claude", rules.REVIEW)):
            item = store.add("all", "x", actor="claude")["id"]
            ok, answer = call(manager, tool, {"item": item, "state": retired}, raw=True)
            assert ok and answer["state"] == current, (tool, retired, answer)
        item = store.add("all", "x", actor="claude")["id"]
        ok, answer = call(manager, tool, {"item": item, "state": "waiting_install", "waiting_on": "a reboot", "wait_kind": "install"}, raw=True)
        assert ok and answer["state"] == rules.WAITING, (tool, answer)
    ok, born = call(manager, "task_manager_add", {"list": "all", "text": "later", "state": "back_burner"}, raw=True)
    assert ok and born["state"] == rules.TODO


def test_an_old_name_runs_the_handler_and_is_logged_under_the_name_the_caller_used(world, manager):  # noqa: F811
    ok, via_old = call(manager, "huddle_list", {"list": "all"}, raw=True)
    ok_new, via_new = call(manager, "task_manager_tasks_list", {"list": "all"}, raw=True)
    assert ok and ok_new and via_old.keys() == via_new.keys()
    assert mcp_events.flush(10)
    assert [e["tool"] for e in mcp_events.recent(tool="huddle_list")] == ["huddle_list"]
    assert [e["tool"] for e in mcp_events.recent(tool="task_manager_tasks_list")] == ["task_manager_tasks_list"]
    rollup.run(datetime.now(timezone.utc), world.usage)
    counted = {row[1]: row[4] for row in world.usage.rows_between("0000-00-00", "9999-99-99")}
    assert counted["huddle_list"] == 1 and counted["task_manager_tasks_list"] == 1


def test_a_disabled_plugin_refuses_an_old_name_like_a_new_one(manager):  # noqa: F811
    set_state(manager, enabled=False)
    listed = {d["name"] for d in tools.tool_definitions()}
    assert not listed & {"huddle_list", "task_manager_tasks_list", "huddle_add", "task_manager_add"}
    for name in ("huddle_list", "task_manager_tasks_list"):
        assert not cplug_mcp.available(name)
        ok, text = call(manager, name, {"list": "all"}, raw=True)
        assert not ok and "disabled" in text, name


def test_an_agent_write_by_an_old_name_still_needs_agent_writes(manager):  # noqa: F811
    set_state(manager, grants=("sessions.read", "notify"))
    ok, text = call(manager, "huddle_add", {"list": "all", "text": "y"}, raw=True)
    assert not ok and "agent_writes" in text


def test_an_external_tokens_old_name_write_parks_under_the_current_name(manager, monkeypatch):  # noqa: F811
    from src.core.mcp import write_tools

    parked = []

    async def park(manager, caller, target_id, target_tmux, name, summary, shown, run, key):
        parked.append(name)
        return {"content": [{"type": "text", "text": json.dumps({"status": "pending", "id": "act_1"})}]}

    monkeypatch.setattr(write_tools, "park", park)
    external = AgentCaller("mcp-token:t", "mcp-token:t", "mcp-token:t", "tok", "write")
    ok, body = call(manager, "huddle_add", {"list": "all", "text": "x"}, caller=external, raw=True)
    assert ok and body["status"] == "pending" and parked == ["task_manager_add"]


def test_a_pending_approval_stored_under_an_old_name_replays_and_hears_its_denial_as_the_current_one():
    item = pending.PendingAction(id="act_1", created_at=0.0, caller_session_id="s", caller_tmux="t", target_session_id="", target_tmux="",
                                 action="huddle_item_state_request", args_summary="x", execute=None, args={"item": 1}, dedupe_key="")
    assert approval_runtime.expected_of(item)["action"] == "task_manager_state_request"
    assert {"huddle_item_state_request", "task_manager_state_request"} <= set(pending._DENY_HOOKS)


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


from __future__ import annotations

from src.core.mcp import beast_mode, tools
from src.core.mcp.approvals import call_context
from tests.python.mcp.test_mcp_context_budget import MAX_DESCRIPTION_CHARS

CONTRACT = {"description", "project_id", "misfire", "retry_max", "retry_backoff_s", "max_runtime_s"}


def _defs():
    return {d["name"]: d for d in tools.tool_definitions(None) if d["name"].startswith("automation")}


def test_create_and_update_list_the_contract_fields_and_the_new_target_kinds():
    defs = _defs()
    for name in ("automation_create", "automation_update"):
        props = defs[name]["inputSchema"]["properties"]
        assert CONTRACT <= set(props)
        text = props["target"]["description"]
        for word in ("session_message", "command", "sequence", "sleep_idle_sessions", "send_notification"):
            assert word in text
    assert "automation_changes" in defs and defs["automation_changes"]["inputSchema"]["required"] == ["automation_id"]


def test_automation_tool_descriptions_stay_inside_the_budget():
    assert _defs() and all(len(d["description"]) <= MAX_DESCRIPTION_CHARS for d in _defs().values())


def test_the_new_write_tools_wait_for_the_owner_unless_beast_covers_them():
    for name in ("automation_log_settings_update", "automation_commands_set"):
        assert name not in beast_mode.ALWAYS_WAITS and name in call_context.GATED_TOOLS
        assert name in tools.WRITE_TOOLS

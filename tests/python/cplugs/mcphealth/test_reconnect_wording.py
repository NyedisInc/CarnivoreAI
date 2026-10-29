
import json
from datetime import datetime, timezone

from src.core.mcp_health import disabled
from src.core.mcp_health.fold import extract_mcp_events, fold_mcp_health
from src.core.mcp_health.history import reset_history, scan_mcp_events

FAILED = {"type": "attachment", "timestamp": "2026-10-09T19:00:00.000Z", "attachment": {
    "type": "deferred_tools_delta", "addedNames": [], "removedNames": [], "pendingMcpServers": [],
    "failedMcpServers": [
        {"name": "carnivore", "errorCode": "ECONNREFUSED", "error": "ECONNREFUSED: x"},
        {"name": "higgsfield", "errorCode": "ENDPOINT_NOT_FOUND", "error": "MCP endpoint not found"}]}}
RECONNECT = [
    {"parentUuid": "a", "isSidechain": False, "promptId": "p", "type": "user", "isMeta": True,
     "message": {"role": "user", "content": "<local-command-caveat>The command below was run directly in Claude "
                 "Code, not sent to you as a request, and its output goes straight to the user. It's recorded here "
                 "as context for later messages.</local-command-caveat>"}, "timestamp": "2026-10-09T19:31:55.988Z"},
    {"parentUuid": "b", "isSidechain": False, "promptId": "p", "type": "user",
     "message": {"role": "user", "content": "<command-name>/mcp</command-name>\n            "
                 "<command-message>mcp</command-message>\n            <command-args>reconnect carnivore</command-args>"},
     "timestamp": "2026-10-09T19:31:55.988Z"},
    {"parentUuid": "c", "isSidechain": False, "promptId": "p", "type": "user",
     "message": {"role": "user", "content": "<local-command-stdout>Successfully reconnected to carnivore"
                 "</local-command-stdout>"}, "timestamp": "2026-10-09T19:31:55.988Z"},
]


def _names(records):
    return sorted(d.name for d in fold_mcp_health(extract_mcp_events(records)).dropped)


def test_successfully_reconnected_clears_that_server_only():
    assert _names([FAILED]) == ["carnivore", "higgsfield"]
    assert _names([FAILED] + RECONNECT) == ["higgsfield"]


def test_the_history_scan_keeps_the_new_wording_past_the_tail(tmp_path):
    reset_history()
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in [FAILED] + RECONNECT))
    events = scan_mcp_events(str(path), 0, path.stat().st_size)
    assert sorted(d.name for d in fold_mcp_health(events).dropped) == ["higgsfield"]


def test_a_failure_line_in_the_new_wording_does_not_heal():
    bad = json.loads(json.dumps(RECONNECT))
    bad[2]["message"]["content"] = "<local-command-stdout>Failed to reconnect to carnivore</local-command-stdout>"
    assert _names([FAILED] + bad) == ["carnivore", "higgsfield"]


def test_disabled_servers_come_from_project_settings_and_follow_edits(tmp_path):
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    assert disabled.disabled_servers(str(tmp_path)) == frozenset()
    (settings_dir / "settings.local.json").write_text(json.dumps({"disabledMcpjsonServers": ["higgsfield"]}))
    assert disabled.disabled_servers(str(tmp_path)) == {"higgsfield"}
    (settings_dir / "settings.json").write_text(json.dumps({"disabledMcpjsonServers": ["Claude.ai Docs"]}))
    assert disabled.disabled_servers(str(tmp_path)) == {"higgsfield", "claude_ai_docs"}
    (settings_dir / "settings.local.json").write_text("{not json")
    assert disabled.disabled_servers(str(tmp_path)) == {"claude_ai_docs"}
    assert disabled.disabled_servers(None) == frozenset()

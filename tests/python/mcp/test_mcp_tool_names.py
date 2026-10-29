
from __future__ import annotations

import re

from src.core.mcp import aliases, tools

VERBS = frozenset({
    "list", "get", "create", "update", "delete", "set", "rename", "move", "archive", "unarchive", "add", "remove", "copy",
    "pin", "unpin", "wake", "stop", "restart", "interrupt", "purge", "run", "cancel", "continue", "preview", "fix", "rebuild",
    "import", "export", "activate", "dismiss", "snooze", "send", "reply", "wait", "watch", "ask", "fork", "spawn", "focus",
    "answer", "lookup", "search", "check", "chat", "embed", "decide", "branch", "rewind", "pack", "unpack", "reconnect", "request",
})
VIEW_NOUNS = frozenset({"status", "output", "log", "changes", "guide", "inbox", "thread", "backlog", "ledger", "manifest", "profile",
                        "roster"})
KEPT = {
    "whoami": "a one-word identity read every agent knows",
    "task_manager_scratch_post": "Joe (ccsliinc)'s #1758 word: a client posts to a scratch board; create would read as always new",
    "task_manager_scratch_clear": "Joe (ccsliinc)'s #1758 word, 'until I clear it'; delete would read as removing the Scratch task too",
    "notify": "the one self-notification verb, no family",
    "widget_bars_reset": "reset is the owner's own word ('reset bars to defaults'); set would read as a write of a value",
    "session_read_output": "verb-object phrase called constantly by agents outside this repo",
    "session_send_keys": "verb-object phrase called constantly by agents outside this repo",
    "session_send_message": "verb-object phrase called constantly by agents outside this repo",
    "session_notes_put": "named in the server instructions and every pane's habits; proposed session_notes_set",
    "automation_run_now": "run is the verb; now keeps it apart from automation_run_*, whose run is a noun",
    "alerts_dismiss_resolved": "one bulk verb over a filter; a verb-last spelling reads worse",
    "alert_open_system_settings": "verb-object phrase naming the macOS settings pane an alert's fix opens; open is not a record verb",
    "beastmode_off": "deliberately one-way (no tool turns it on), so no _set",
    "autonomy_off": "the tray's Stand Down (#1897): deliberately one-way (beast off, swarm off, scheduler paused), so no _set",
    "skills_command_center": "names the screen it reads",
    "project_replica_list": "the P2 contract name (docs/pack.md 5): the replicas of one project, a per-project read",
    "project_sync": "the P3 contract name (docs/pack.md 5): carry new commits to a replica, a verb-object phrase",
    "project_publish_repo": "the P3 contract name (docs/pack.md 5): create a private repo for the project",
    "project_migrate_plan": "the P4 contract name (docs/pack.md 5): the read-only plan of a migrate, paired with project_migrate",
    "company_migrate_plan": "the P4 contract name (docs/pack.md 5): the read-only plan of a company migrate, paired with company_migrate",
    "project_migrate": "the P4 contract name (docs/pack.md 5): move a project to another computer, a verb-object phrase",
    "company_migrate": "the P4 contract name (docs/pack.md 5): move a company's projects to another computer",
    "project_migrate_back": "the P4 contract name (docs/pack.md 5): bring a moved-away project home",
    "placement_explain": "the P7 contract name (docs/pack.md 5): a computed what-if read, named for the question it answers",
    "computer_invite": "PLAN D7 contract name: open a code for adding a computer",
    "session_shell_open": "the F2b contract name (#1551): open the agent's shell, creating it on first use; create would read as always new",
    "computer_leave": "the verb the computers panel shows: leave the pack this computer joined",
    "stats_feed": "the contract name of #1547 (docs/stats-feed.md): the one token-throughput feed, named for the feed it reads",
    "browser_open": "Joe's request (huddle item 'open huddle pages in a side browser', docs/browser-pages.md): open a page on his screen as a browser session, as the pane shell tool opens a shell; create would hide the reuse of a pool session",
    "mcp_usage": "names the server it counts (the mcp-usage route, #1752); usage is the computed view, as usage_ledger's ledger is",
    "sidebar_show": "Joe's request (#1868): show a left bar item in the window he used last; show is the word he used, and focus/open already mean other things (huddle_focus selects an item, browser_open opens a row)",
    "crate_backup_families": "Joe (ccsliinc)'s crate tool (docs/crate.md): the backup families a crate export can include, named for what it reads; list would read as plural records of one kind",
    "crate_import_undo": "Joe (ccsliinc)'s #1912 word (docs/crate-import.md): undo a finished restore; delete would read as removing the crate",
    "files_open": "Joe's request (#1724): open a file into his files list, as browser_open opens a page; the open_files route is POST /files/open",
    "session_attach_command": "the R1-14 contract name (#2328, PLAN row): the argv that attaches a terminal, named for the command it returns; get would hide what comes back",
}
UNCHECKED_PREFIXES = ("swarm_",)
_SHAPE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def violation(name: str) -> str:
    if not _SHAPE.match(name):
        return "not lowercase snake case with a family prefix"
    parts = name.split("_")
    last = parts[-1]
    if last not in VERBS and last not in VIEW_NOUNS:
        return f"last token {last!r} is neither a verb nor a view noun"
    if last == "list" and not parts[-2].endswith("s"):
        return f"a collection read takes a plural noun before _list, not {parts[-2]!r}"
    return ""


def test_every_registered_tool_name_fits_the_scheme():
    bad = {n: why for n in tools._TOOLS if n not in KEPT and not aliases.is_alias(n) and not n.startswith(UNCHECKED_PREFIXES) and (why := violation(n))}
    assert bad == {}, f"rename to fit docs/mcp-server.md 'Tool names', or add to KEPT with a reason: {bad}"


def test_kept_names_are_still_registered():
    assert sorted(set(KEPT) - set(tools._TOOLS)) == []


def test_the_check_can_go_red():
    assert violation("company_set_hq") and violation("automation_commands") and violation("bookmark_list")
    assert violation("automation_log_settings") and violation("Sessions_list")
    assert not violation("automations_list") and not violation("company_hq_set") and not violation("session_status")


def test_no_huddle_name_is_kept_by_exception():
    assert [n for n in KEPT if n.startswith("huddle_")] == []


def test_every_retired_name_is_skipped_only_through_the_alias_table():
    unfit = {n for n in tools._TOOLS if n not in KEPT and not n.startswith(UNCHECKED_PREFIXES) and violation(n)}
    assert unfit and all(aliases.is_alias(n) for n in unfit), unfit

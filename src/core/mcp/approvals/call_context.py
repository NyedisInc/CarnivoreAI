
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional

ARG = "huddle_item"

GATED_TOOLS = frozenset({
    "session_create", "session_send_keys", "session_restart", "session_stop", "session_delete", "session_purge",
    "agent_spawn", "agent_fork", "crosstalk_send", "crosstalk_reply",
    "bookmark_branch", "bookmark_rewind", "swarm_rewind", "swarm_spawn", "swarm_set_look", "swarm_rename",
    "project_rename", "company_create", "company_rename", "company_parent_set",
    "company_hq_set", "company_delete", "project_archive", "project_unarchive", "project_move", "project_pack", "project_unpack", "board_import", "pipeline_plugin_rebuild",
    "cplug_update",
    "session_wake", "session_shell_open", "session_interrupt", "session_dialog_answer", "session_dialog_questions_answer", "project_create", "project_delete", "project_replica_add", "project_replica_remove", "project_air_gap_set", "dashboard_delete",
    "project_sync", "project_github_account_set", "project_publish_repo", "pack_gh_login_add",
    "project_migrate", "company_migrate", "project_migrate_back", "session_move", "session_folder_move", "session_send",
    "mod_enabled_set", "mod_remove", "skill_copy", "skill_remove",
    "automation_create", "automation_update", "automation_delete", "automation_run_now", "automation_run_cancel", "automation_finding_fix", "automation_run_continue",
    "automation_log_settings_update", "automation_commands_set", "automation_scheduler_set",
    "messaging_conversation_add", "messaging_binding_create", "messaging_binding_delete",
    "session_description_set", "project_description_set", "project_color_set", "company_color_set",
    "computer_invite", "computer_remove", "computer_direction_set", "computer_leave", "computer_add",
    "session_send_message", "swarm_card_grant", "swarm_card_pace",
})
ACTION_TOOLS = {"crosstalk_resume": "crosstalk_send"}


@dataclass
class Call:

    tool: str
    args: Dict[str, Any]


@dataclass
class Replay:

    action_id: str
    expected: Dict[str, Any] = field(default_factory=dict)
    consumed: bool = False
    refused: str = ""


CURRENT: contextvars.ContextVar[Optional[Call]] = contextvars.ContextVar("mcp_current_call", default=None)
REPLAY: contextvars.ContextVar[Optional[Replay]] = contextvars.ContextVar("mcp_approval_replay", default=None)


def strip_legacy_arg(name: str, args: Dict[str, Any], gated: frozenset) -> Dict[str, Any]:
    if name not in gated or ARG not in args:
        return args
    return {k: v for k, v in args.items() if k != ARG}


@contextmanager
def calling(name: str, args: Dict[str, Any]) -> Iterator[Call]:
    call = Call(tool=name, args=args)
    token = CURRENT.set(call)
    try:
        yield call
    finally:
        CURRENT.reset(token)


@contextmanager
def replaying(replay: Replay) -> Iterator[Replay]:
    token = REPLAY.set(replay)
    try:
        yield replay
    finally:
        REPLAY.reset(token)


def take_replay() -> Optional[Replay]:
    replay = REPLAY.get()
    if replay is None or replay.consumed:
        return None
    replay.consumed = True
    return replay

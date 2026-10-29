
from __future__ import annotations


from src.core.session_status import (
    STATUS_DEAD,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    derive_read_state,
)


EVENT_STOP = "Stop"
EVENT_NOTIFICATION = "Notification"
EVENT_PERMISSION_REQUEST = "PermissionRequest"
EVENT_USER_PROMPT_SUBMIT = "UserPromptSubmit"
EVENT_PRE_TOOL_USE = "PreToolUse"
EVENT_POST_TOOL_USE = "PostToolUse"
EVENT_SUBAGENT_START = "SubagentStart"
EVENT_SUBAGENT_STOP = "SubagentStop"

WORKING_HEARTBEAT_TIMEOUT_SECONDS: int = 120


def map_tmux_fallback(tmux_status: str, unread: bool = False) -> str:
    if tmux_status == STATUS_DEAD:
        return STATUS_DEAD
    if tmux_status == STATUS_RUNNING:
        return STATUS_UNKNOWN
    if tmux_status == STATUS_IDLE:
        return derive_read_state(STATUS_IDLE, unread=unread)
    return STATUS_UNKNOWN

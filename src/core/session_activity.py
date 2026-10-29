
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import structlog

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

logger = structlog.get_logger(__name__)


def map_tmux_fallback(tmux_status: str, unread: bool = False) -> str:
    if tmux_status == STATUS_DEAD:
        return STATUS_DEAD
    if tmux_status == STATUS_RUNNING:
        return STATUS_UNKNOWN
    if tmux_status == STATUS_IDLE:
        return derive_read_state(STATUS_IDLE, unread=unread)
    return STATUS_UNKNOWN


@dataclass
class SessionActivitySignal:

    permission_open: bool = False
    permission_opened_at: Optional[datetime] = None
    # permission prompt
    notice_open: bool = False


class SessionActivityTracker:

    def __init__(self) -> None:
        self._signals: dict[str, SessionActivitySignal] = {}

    def clear_notice(self, session_id: str) -> bool:
        state = self._signals.get(session_id)
        if state is None or not state.notice_open:
            return False
        state.notice_open = False
        logger.debug("notice_cleared_by_view", session_id=session_id)
        return True

    def clear_permission(self, session_id: str) -> bool:
        state = self._signals.get(session_id)
        if state is None or not state.permission_open:
            return False
        state.permission_open = False
        state.permission_opened_at = None
        return True

    def permission_open_since(self, session_id: str) -> Optional[datetime]:
        state = self._signals.get(session_id)
        if state is None or not state.permission_open:
            return None
        return state.permission_opened_at

    def forget(self, session_id: str) -> None:
        self._signals.pop(session_id, None)

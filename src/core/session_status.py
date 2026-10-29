
from __future__ import annotations

from typing import Optional

STATUS_RUNNING: str = "running"
STATUS_IDLE: str = "idle"
STATUS_DEAD: str = "dead"
STATUS_UNKNOWN: str = "unknown"

ALL_STATUSES: frozenset[str] = frozenset(
    {STATUS_RUNNING, STATUS_IDLE, STATUS_DEAD, STATUS_UNKNOWN}
)


STATUS_QUESTION: str = "question"

STATUS_NOTICE: str = "notice"

STATUS_WORKING: str = "working"

STATUS_WORKING_SUBAGENT: str = "working_subagent"

STATUS_FINISHED_UNREAD: str = "finished_unread"

ALL_ACTIVITY_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_DEAD,
        STATUS_QUESTION,
        STATUS_NOTICE,
        STATUS_WORKING,
        STATUS_WORKING_SUBAGENT,
        STATUS_FINISHED_UNREAD,
        STATUS_IDLE,
        STATUS_UNKNOWN,
    }
)

ACTIVITY_STATUS_PRIORITY: tuple[str, ...] = (
    STATUS_DEAD,
    STATUS_QUESTION,
    STATUS_NOTICE,
    STATUS_WORKING_SUBAGENT,
    STATUS_WORKING,
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_UNKNOWN,
)



READ_STATE_PAIR: tuple[str, str] = (STATUS_IDLE, STATUS_FINISHED_UNREAD)


def derive_read_state(state: Optional[str], *, unread: bool) -> Optional[str]:
    if state not in READ_STATE_PAIR:
        return state
    return STATUS_FINISHED_UNREAD if unread else STATUS_IDLE


KNOWN_SHELL_COMMANDS: frozenset[str] = frozenset(
    {"zsh", "bash", "sh", "dash", "ksh", "fish", "tcsh", "csh"}
)


def resolve_pane_status(
    pane_dead: Optional[str], pane_current_command: Optional[str]
) -> str:
    if pane_dead is None or pane_current_command is None:
        return STATUS_UNKNOWN

    if pane_dead.strip() == "1":
        return STATUS_DEAD

    cmd = pane_current_command.strip().lower()
    if not cmd:
        return STATUS_UNKNOWN

    if cmd in KNOWN_SHELL_COMMANDS:
        return STATUS_IDLE

    return STATUS_RUNNING



LIVENESS_LIVE: str = "live"

LIVENESS_GONE: str = "gone"

LIVENESS_UNKNOWN: str = "unknown"


def resolve_listing_liveness(
    exists: Optional[bool], pane_status: Optional[str]
) -> str:
    if exists is None:
        return LIVENESS_UNKNOWN
    if not exists:
        return LIVENESS_GONE
    if pane_status is None:
        return LIVENESS_LIVE
    if pane_status == STATUS_DEAD:
        return LIVENESS_GONE
    if pane_status == STATUS_UNKNOWN:
        return LIVENESS_UNKNOWN
    return LIVENESS_LIVE

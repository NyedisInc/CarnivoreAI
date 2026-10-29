"""What one stored session row IS, for the projects page. Pure.

Five states, and the order they are decided in is the rule:

  running  ``lifecycle='running'``. FIRST, even over ``archived_at``: the
           schema guarantees archiving never hides a live process (design
           section 4.8, ``session_store.list_sessions``), so a running row
           that was also removed from the lists still reads running.
  removed  ``archived_at`` is set: the user took it off their lists
           (``DELETE /sessions/records/{uuid}``), the row is kept.
  asleep   stopped by a sleep (``session_sleep.is_asleep``), wakeable.
  closed   any other stopped row: ended, killed, or a ghost the lifecycle
           reaper stopped when its tmux session was measured gone.
  unknown  ``lifecycle='unknown'``: CANNOT DETERMINE, never folded into
           closed, because "we could not look" is not "it ended".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Tuple

from src.core.db_models import (
    SESSION_FAMILY_SOURCE_NOT_LAUNCHED,
    SESSION_LIFECYCLE_RUNNING,
    SESSION_LIFECYCLE_STOPPED,
)
from src.core.session_sleep import is_asleep

STATE_RUNNING = "running"
STATE_ASLEEP = "asleep"
STATE_CLOSED = "closed"
STATE_REMOVED = "removed"
STATE_UNKNOWN = "unknown"

HISTORY_STATES: Tuple[str, ...] = (
    STATE_RUNNING,
    STATE_ASLEEP,
    STATE_CLOSED,
    STATE_REMOVED,
    STATE_UNKNOWN,
)

_ACTIVITY_COLUMNS: Tuple[str, ...] = ("last_work_at", "last_seen_running_at", "created_at")


def row_state(row: Mapping[str, Any]) -> str:
    lifecycle = row.get("lifecycle")
    if lifecycle == SESSION_LIFECYCLE_RUNNING:
        return STATE_RUNNING
    if row.get("archived_at"):
        return STATE_REMOVED
    if is_asleep(row):
        return STATE_ASLEEP
    if lifecycle == SESSION_LIFECYCLE_STOPPED:
        return STATE_CLOSED
    return STATE_UNKNOWN


def parse_stamp(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def activity_at(row: Mapping[str, Any]) -> Optional[datetime]:
    stamps = [parse_stamp(row.get(column)) for column in _ACTIVITY_COLUMNS]
    known = [stamp for stamp in stamps if stamp is not None]
    return max(known) if known else None


def display_title(row: Mapping[str, Any]) -> str:
    for column in ("title", "claude_title", "tmux_name", "session_uuid"):
        value = row.get(column)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def iso(stamp: Optional[datetime]) -> Optional[str]:
    if stamp is None:
        return None
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


NON_AGENT_KINDS = frozenset({"browser", "layout"})
SHELL_FAMILY = "shell"


def is_agent_row(row: Mapping[str, Any], family: Optional[str]) -> bool:
    if row.get("kind") in NON_AGENT_KINDS:
        return False
    name = str(family or row.get("agent_family") or "").strip().lower()
    if not name and row.get("agent_family_source") == SESSION_FAMILY_SOURCE_NOT_LAUNCHED:
        return False
    return name != SHELL_FAMILY


from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import structlog

from src.core.db_models import DEFAULT_TMUX_SOCKET
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope
from src.core.session_activity import WORKING_HEARTBEAT_TIMEOUT_SECONDS
from src.core.session_status import (
    STATUS_DEAD,
    STATUS_UNKNOWN,
    derive_read_state,
)

logger = structlog.get_logger(__name__)

STALE_AFTER = timedelta(seconds=WORKING_HEARTBEAT_TIMEOUT_SECONDS + 60)

PERISHABLE = ("working", "working_subagent", "question", "notice")


RESTORE_OK = "restored"
RESTORE_STALE = "stale"
RESTORE_ABSENT = "absent"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(stamp: Optional[str]) -> Optional[datetime]:
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def restore_state(
    state: Optional[str],
    stamped_at: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Tuple[Optional[str], str]:
    if not state:
        return (None, RESTORE_ABSENT)
    if state in (STATUS_DEAD, STATUS_UNKNOWN):
        return (None, RESTORE_ABSENT)
    when = _parse(stamped_at)
    if when is None:
        return (None, RESTORE_STALE)
    age = (now or datetime.now(timezone.utc)) - when
    if state in PERISHABLE and age > STALE_AFTER:
        return (None, RESTORE_STALE)
    return (state, RESTORE_OK)


def write_state(
    conn,
    tmux_name: str,
    state: str,
    tmux_created_epoch: Optional[int],
    *,
    tmux_socket: str = DEFAULT_TMUX_SOCKET,
    now: Optional[str] = None,
    host_key: str = LOCAL_HOST_KEY,
) -> bool:
    if not tmux_name or not state:
        return False
    state = derive_read_state(state, unread=False) or state
    if tmux_created_epoch is None:
        logger.debug(
            "activity_state_write_no_epoch",
            tmux_name=tmux_name,
            note=(
                "no tmux_created_epoch was supplied, so the exact "
                "instance cannot be identified. Refusing the write "
                "rather than falling back to a name-scoped UPDATE that "
                "could stamp a dead session's row with a live one's "
                "status"
            ),
        )
        return False
    try:
        scope_sql, scope_params = host_scope(conn, host_key)
        cur = conn.execute(
            "UPDATE sessions SET activity_state = ?, activity_state_at = ? "
            "WHERE tmux_socket = ? AND tmux_name = ? "
            f"AND tmux_created_epoch = ?{scope_sql}",
            (
                state,
                now or utc_now_iso(),
                tmux_socket,
                tmux_name,
                int(tmux_created_epoch),
                *scope_params,
            ),
        )
        return bool(cur.rowcount)
    except Exception as exc:  # noqa: BLE001
        logger.debug("activity_state_write_failed", error=str(exc))
        return False

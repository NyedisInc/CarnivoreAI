
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

import structlog

from src.core import resource_push
from src.core.resource_push import topics as resource_topics

from src.core.subagents.parent_index import parse_timestamp
from src.core.hosts.ddl import LOCAL_HOST_KEY, host_scope

logger = structlog.get_logger(__name__)

PROJECTS_NOTIFY_MIN_INTERVAL_SECONDS = 60.0

SOURCE_EXACT_EPOCH = "exact_epoch"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_instance_row(
    conn: sqlite3.Connection,
    tmux_name: str,
    *,
    tmux_socket: str,
    tmux_created_epoch: Optional[int],
    host_key: str = LOCAL_HOST_KEY,
) -> Tuple[Optional[int], Optional[str]]:
    if not tmux_name or tmux_created_epoch is None:
        return (None, None)
    scope_sql, scope_params = host_scope(conn, host_key)
    row = conn.execute(
        "SELECT id FROM sessions "
        f"WHERE tmux_socket = ?{scope_sql} AND tmux_name = ? AND tmux_created_epoch = ?",
        (tmux_socket, *scope_params, tmux_name, int(tmux_created_epoch)),
    ).fetchone()
    if row is None:
        return (None, None)
    return (int(row[0]), SOURCE_EXACT_EPOCH)


def stamp_work(
    conn: sqlite3.Connection,
    tmux_name: str,
    *,
    tmux_socket: str,
    tmux_created_epoch: Optional[int],
    now: Optional[str] = None,
) -> Optional[str]:
    """Record that work just happened in one session.

    Description: writes ``sessions.last_work_at`` on the single row
      ``resolve_instance_row`` identifies, and on no other. Callers must
      only reach here for a ``claude_hooks.WORK_EVENTS`` kind; this
      function does not re-check the kind because a second copy of that
      rule is a second place for it to drift.

      BEST-EFFORT, LIKE EVERY WRITE ON THE HOOK PATH. An ordering key
      that could not be updated must never turn hook delivery into an
      error for the session that was working. A refusal is logged with
      its reason and returns None, which the caller distinguishes from a
      write.

      MONOTONIC: an instant that is not strictly newer than the row's
      current value (both parsed, so ``...21.5Z`` and ``...21.500000Z``
      compare as equal) is refused and returns None. An unparseable
      current value is overwritten.
    Inputs: conn (sqlite3.Connection) - the caller owns the transaction.
      tmux_name (str). tmux_socket (str). tmux_created_epoch (int | None).
      now (str | None) - the ISO instant the work happened; None is now.
    Output: str | None - the resolution source when a row was stamped,
      None when nothing was written.
    Example: stamp_work(conn, 'cloude_Mac', tmux_socket='cloude')
    """
    if not tmux_name:
        return None
    try:
        row_id, source = resolve_instance_row(
            conn,
            tmux_name,
            tmux_socket=tmux_socket,
            tmux_created_epoch=tmux_created_epoch,
        )
    except sqlite3.Error as exc:
        logger.debug("work_stamp_resolve_failed", tmux_name=tmux_name, error=str(exc))
        return None
    if row_id is None:
        logger.debug(
            "work_stamp_no_instance_row",
            tmux_name=tmux_name,
            tmux_created_epoch=tmux_created_epoch,
            note=(
                "no sessions row carries this exact tmux instance, so there "
                "is nothing to stamp. Refusing rather than falling back to "
                "a name-scoped write"
            ),
        )
        return None
    value = now or utc_now_iso()
    try:
        current = conn.execute(
            "SELECT last_work_at FROM sessions WHERE id = ?", (row_id,)
        ).fetchone()
        held = parse_timestamp(current[0]) if current else None
        offered = parse_timestamp(value)
        if held is not None and offered is not None and offered <= held:
            return None
        cur = conn.execute(
            "UPDATE sessions SET last_work_at = ? WHERE id = ?",
            (value, row_id),
        )
    except sqlite3.Error as exc:
        logger.debug("work_stamp_write_failed", tmux_name=tmux_name, error=str(exc))
        return None
    return source if cur.rowcount else None


def persist_instance_stamp(
    open_connection: Callable[[], Optional[sqlite3.Connection]],
    session_id: str,
    tmux_name: str,
    *,
    tmux_socket: str,
    tmux_created_epoch: int,
    at: Optional[str] = None,
) -> Optional[str]:
    """Open a connection, stamp one instance in a transaction, close it.

    Description: the connection plumbing ``SessionManager._persist_work_stamp``
      runs once its filter and throttle have admitted a stamp. Best-effort:
      every failure is logged at debug and answers None, because an
      ordering key that could not be written must never fail the caller.
    Inputs: open_connection (callable) - returns a writable connection or
      None. session_id (str) - for the log only. tmux_name (str).
      tmux_socket (str). tmux_created_epoch (int). at (str | None) - the
      instant, None meaning now.
    Output: str | None - the resolution source when a row was stamped.
    Example: persist_instance_stamp(mgr._writable_datastore_connection,
      'ses_1', 'cloude_x', tmux_socket='cloude', tmux_created_epoch=1)
    """
    from src.core.db import transaction

    conn = None
    source: Optional[str] = None
    try:
        conn = open_connection()
        if conn is None:
            return None
        with transaction(conn):
            source = stamp_work(
                conn,
                tmux_name,
                tmux_socket=tmux_socket,
                tmux_created_epoch=tmux_created_epoch,
                now=at,
            )
        if source is not None:
            resource_push.notify_coalesced(
                resource_topics.PROJECTS, tmux_name, PROJECTS_NOTIFY_MIN_INTERVAL_SECONDS
            )
        if source is None:
            logger.debug(
                "work_stamp_not_written",
                session_id=session_id,
                tmux_name=tmux_name,
                note="no row matched the instance, or the instant was not newer",
            )
    except (sqlite3.Error, OSError) as exc:
        logger.debug("work_stamp_persist_failed", session_id=session_id, error=str(exc))
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error as exc:
                logger.debug("work_stamp_close_failed", error=str(exc))
    return source

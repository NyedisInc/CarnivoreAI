from __future__ import annotations

import sqlite3
from typing import Any, Dict

import structlog

from src.core.db import table_exists, transaction
from src.core.library_cleanup.errors import CleanupNotFound, CleanupRefused

logger = structlog.get_logger()

REFUSE_NOT_ARCHIVED = "not_archived"
REFUSE_LIVE = "live_session"
REFUSE_HAS_CHILDREN = "has_children"
REFUSE_SWARM_AGENT = "swarm_agent"
REFUSE_REFERENCED = "still_referenced"
LIFECYCLE_RUNNING = "running"

UUID_KEYED_TABLES = ("session_notes", "session_group_membership", "session_conversations")


def _blocked_reason(conn: sqlite3.Connection, row_id: int) -> "tuple[str, str] | None":
    children = conn.execute("SELECT COUNT(*) FROM sessions WHERE parent_session_id = ?", (row_id,)).fetchone()[0]
    if children:
        return REFUSE_HAS_CHILDREN, f"{children} session rows name this row as their parent"
    if table_exists(conn, "swarm_agents") and conn.execute(
            "SELECT 1 FROM swarm_agents WHERE session_row_id = ?", (row_id,)).fetchone():
        return REFUSE_SWARM_AGENT, "a Swarm agent still uses this session; retire the agent first"
    return None


def _delete_row(conn: sqlite3.Connection, row_id: int, session_uuid: str) -> Dict[str, int]:
    removed: Dict[str, int] = {}
    try:
        for table in UUID_KEYED_TABLES:
            if table_exists(conn, table):
                removed[table] = conn.execute(f"DELETE FROM {table} WHERE session_uuid = ?", (session_uuid,)).rowcount
        removed["sessions"] = conn.execute("DELETE FROM sessions WHERE id = ?", (row_id,)).rowcount
    except sqlite3.IntegrityError as exc:
        logger.warning("library_session_purge_refused", session_uuid=session_uuid, error=str(exc))
        raise CleanupRefused(REFUSE_REFERENCED, "another record still points at this session") from exc
    return removed


def purge_stopped_rows_of_project(conn: sqlite3.Connection, project_id: int) -> int:
    rows = conn.execute("SELECT id, session_uuid FROM sessions WHERE project_id = ? AND lifecycle = 'stopped'",
                        (project_id,)).fetchall()
    gone = 0
    for row_id, session_uuid in rows:
        if _blocked_reason(conn, row_id) is not None:
            continue
        conn.execute("SAVEPOINT purge_stopped_row")
        try:
            _delete_row(conn, row_id, session_uuid)
        except CleanupRefused:
            conn.execute("ROLLBACK TO purge_stopped_row")
        else:
            gone += 1
        conn.execute("RELEASE purge_stopped_row")
    return gone


def purge_session(conn: sqlite3.Connection, session_uuid: str) -> Dict[str, Any]:
    with transaction(conn):
        row = conn.execute("SELECT id, archived_at, lifecycle FROM sessions WHERE session_uuid = ?",
                           (session_uuid,)).fetchone()
        if row is None:
            raise CleanupNotFound("no_session", f"no session record {session_uuid}")
        row_id, archived_at, lifecycle = row
        if not archived_at:
            raise CleanupRefused(REFUSE_NOT_ARCHIVED,
                                 "soft-delete the row first; a hard purge only takes an archived row")
        if lifecycle == LIFECYCLE_RUNNING:
            raise CleanupRefused(REFUSE_LIVE, "the session is running")
        blocked = _blocked_reason(conn, row_id)
        if blocked is not None:
            raise CleanupRefused(*blocked)
        removed = _delete_row(conn, row_id, session_uuid)
    logger.info("library_session_purged", session_uuid=session_uuid, row_id=row_id, removed=removed)
    return {"session_uuid": session_uuid, "row_id": row_id, "removed": removed}

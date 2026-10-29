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
LIFECYCLE_RUNNING = "running"

UUID_KEYED_TABLES = ("session_notes", "session_group_membership", "session_conversations")


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
        children = conn.execute("SELECT COUNT(*) FROM sessions WHERE parent_session_id = ?",
                                (row_id,)).fetchone()[0]
        if children:
            raise CleanupRefused(REFUSE_HAS_CHILDREN,
                                 f"{children} session rows name this row as their parent")
        removed: Dict[str, int] = {}
        for table in UUID_KEYED_TABLES:
            if table_exists(conn, table):
                removed[table] = conn.execute(f"DELETE FROM {table} WHERE session_uuid = ?",
                                              (session_uuid,)).rowcount
        removed["sessions"] = conn.execute("DELETE FROM sessions WHERE id = ?", (row_id,)).rowcount
    logger.info("library_session_purged", session_uuid=session_uuid, row_id=row_id, removed=removed)
    return {"session_uuid": session_uuid, "row_id": row_id, "removed": removed}

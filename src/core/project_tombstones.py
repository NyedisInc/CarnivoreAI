
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional, Set

import structlog

from src.core.db import get_meta, table_exists
from src.core.db_models import META_PROJECT_TOMBSTONES_LEGACY_GAP
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

TOMBSTONES_TABLE = "project_tombstones"


def record_tombstone(
    conn: sqlite3.Connection,
    root: str,
    display_name: Optional[str] = None,
    *,
    now: Optional[str] = None,
) -> None:
    if not table_exists(conn, TOMBSTONES_TABLE):
        logger.warning(
            "project_tombstone_table_absent",
            root=root,
            note=(
                "schema is below v5, so this deletion leaves no trace and "
                "a later reconcile will report the root as undetermined "
                "rather than importing it"
            ),
        )
        return
    conn.execute(
        "INSERT INTO project_tombstones (root, display_name, deleted_at) "
        "VALUES (?, ?, ?) ON CONFLICT(root) DO UPDATE SET "
        "display_name = excluded.display_name, deleted_at = excluded.deleted_at",
        (root, display_name, now or utc_now()),
    )


def read_tombstone(conn: sqlite3.Connection, root: str) -> Optional[Dict[str, Any]]:
    if not table_exists(conn, TOMBSTONES_TABLE):
        return None
    row = conn.execute("SELECT root, display_name, deleted_at FROM project_tombstones WHERE root = ?", (root,)).fetchone()
    return None if row is None else {"root": row[0], "display_name": row[1], "deleted_at": row[2]}


def clear_tombstone(conn: sqlite3.Connection, root: str) -> None:
    if not table_exists(conn, TOMBSTONES_TABLE):
        return
    conn.execute("DELETE FROM project_tombstones WHERE root = ?", (root,))


def tombstoned_roots(conn: sqlite3.Connection) -> Set[str]:
    """Every root recorded as deliberately deleted.

    Inputs: conn (sqlite3.Connection).
    Output: set[str] - empty when the table does not exist yet, which is
      NOT the same claim as "nothing was deleted". The caller must read
      ``legacy_gap`` to know which of those two it is looking at.
    Example: "/Users/example/dev/app" in tombstoned_roots(conn)
    """
    if not table_exists(conn, TOMBSTONES_TABLE):
        return set()
    return {
        row[0]
        for row in conn.execute("SELECT root FROM project_tombstones").fetchall()
    }


def legacy_gap(conn: sqlite3.Connection) -> bool:
    raw = get_meta(conn, META_PROJECT_TOMBSTONES_LEGACY_GAP)
    if raw is None:
        return True
    return str(raw) == "1"

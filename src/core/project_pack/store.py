
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

import structlog

from src.core import resource_push
from src.core.db import table_exists, transaction
from src.core.project_pack import constants as K
from src.core.resource_push import topics as resource_topics
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

COLUMNS = (
    "state", "archive_name", "archive_sha256", "archive_bytes", "archive_mtime_ns", "logical_bytes", "file_count",
    "packed_at", "packed_in", "job_id", "job_started_at", "last_error", "accepted_local_only",
)


def get(conn: sqlite3.Connection, project_id: int) -> Optional[Dict[str, Any]]:
    if not table_exists(conn, "project_storage"):
        return None
    row = conn.execute("SELECT * FROM project_storage WHERE project_id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def state_of(conn: sqlite3.Connection, project_id: int) -> str:
    row = get(conn, project_id)
    return row["state"] if row else K.STATE_UNPACKED


def all_rows(conn: sqlite3.Connection) -> Dict[int, Dict[str, Any]]:
    if not table_exists(conn, "project_storage"):
        return {}
    return {r["project_id"]: dict(r) for r in conn.execute("SELECT * FROM project_storage")}


def busy_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    marks = ",".join("?" * len(K.BUSY_STATES))
    if not table_exists(conn, "project_storage"):
        return []
    return [dict(r) for r in conn.execute(f"SELECT * FROM project_storage WHERE state IN ({marks})", K.BUSY_STATES)]


def put(conn: sqlite3.Connection, project_id: int, notify: bool = True, **fields: Any) -> None:
    unknown = set(fields) - set(COLUMNS)
    if unknown:
        raise ValueError(f"unknown project_storage columns: {sorted(unknown)}")
    now = utc_now()
    with transaction(conn):
        exists = conn.execute("SELECT 1 FROM project_storage WHERE project_id = ?", (project_id,)).fetchone()
        if exists:
            if fields:
                sets = ", ".join(f"{c} = ?" for c in fields)
                conn.execute(f"UPDATE project_storage SET {sets}, updated_at = ? WHERE project_id = ?",
                             (*fields.values(), now, project_id))
        else:
            fields.setdefault("state", K.STATE_UNPACKED)
            cols = ", ".join(fields)
            marks = ", ".join("?" * len(fields))
            conn.execute(f"INSERT INTO project_storage (project_id, {cols}, updated_at) VALUES (?, {marks}, ?)",
                         (project_id, *fields.values(), now))
    if notify:
        resource_push.notify(resource_topics.PROJECTS)


def mark_unpacked(conn: sqlite3.Connection, project_id: int, last_error: Optional[str] = None) -> None:
    put(conn, project_id, state=K.STATE_UNPACKED, archive_name=None, archive_sha256=None, archive_bytes=None,
        archive_mtime_ns=None, packed_at=None, packed_in=None, job_id=None, job_started_at=None,
        last_error=last_error, accepted_local_only=None)


def children_of(conn: sqlite3.Connection, parent_id: int) -> List[int]:
    if not table_exists(conn, "project_storage"):
        return []
    return [r["project_id"] for r in conn.execute(
        "SELECT project_id FROM project_storage WHERE packed_in = ?", (parent_id,))]

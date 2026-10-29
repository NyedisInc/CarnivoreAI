
from __future__ import annotations

import sqlite3
from typing import Tuple

DDL_V75: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS project_storage (
        project_id INTEGER PRIMARY KEY,
        state TEXT NOT NULL,
        archive_name TEXT,
        archive_sha256 TEXT,
        archive_bytes INTEGER,
        archive_mtime_ns INTEGER,
        logical_bytes INTEGER,
        file_count INTEGER,
        packed_at TEXT,
        packed_in INTEGER,
        job_id TEXT,
        job_started_at TEXT,
        last_error TEXT,
        accepted_local_only TEXT,
        updated_at TEXT NOT NULL
    )""",
)


def apply_v75(conn: sqlite3.Connection) -> None:
    for statement in DDL_V75:
        conn.execute(statement)

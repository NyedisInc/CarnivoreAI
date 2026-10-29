
from __future__ import annotations

import sqlite3
from typing import Tuple

DDL_V93: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS export_bundles (
        bundle_id      TEXT PRIMARY KEY,
        sha256         TEXT NOT NULL CHECK (length(sha256) = 64),
        scope          TEXT NOT NULL CHECK (scope IN ('session','project')),
        project_uid    TEXT,
        session_uuid   TEXT,
        label          TEXT,
        created_at     REAL NOT NULL,
        locations_json TEXT NOT NULL DEFAULT '[]',
        verified_at    REAL,
        local_removed  INTEGER NOT NULL DEFAULT 0 CHECK (local_removed IN (0,1)),
        updated_at     REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_export_bundles_project ON export_bundles(project_uid)",
    "CREATE INDEX IF NOT EXISTS ix_export_bundles_session ON export_bundles(session_uuid)",
    """CREATE TABLE IF NOT EXISTS export_pointers (
        conversation_id TEXT NOT NULL,
        family          TEXT NOT NULL CHECK (family IN ('claude','codex')),
        bundle_id       TEXT NOT NULL,
        title           TEXT,
        exported_at     REAL NOT NULL,
        PRIMARY KEY (family, conversation_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_export_pointers_bundle ON export_pointers(bundle_id)",
)


def apply_v93(conn: sqlite3.Connection) -> None:
    for statement in DDL_V93:
        conn.execute(statement)

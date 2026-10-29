
from __future__ import annotations

import sqlite3
from typing import Tuple

DDL_V87: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS pack_carried_trust (
        folder            TEXT PRIMARY KEY,
        project_uid       TEXT NOT NULL,
        source_install_id TEXT NOT NULL,
        op_id             TEXT NOT NULL,
        created_at        TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS pack_carried_trust_project ON pack_carried_trust(project_uid)",
)


def apply_v87(conn: sqlite3.Connection) -> None:
    for statement in DDL_V87:
        conn.execute(statement)


IMPORTS_OK_COLUMN = "imports_ok"

V88_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("pack_carried_trust", IMPORTS_OK_COLUMN, f"ALTER TABLE pack_carried_trust ADD COLUMN {IMPORTS_OK_COLUMN} INTEGER NOT NULL DEFAULT 0"),
)


def apply_v88(conn: sqlite3.Connection) -> None:
    for table, column, statement in V88_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)

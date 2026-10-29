
from __future__ import annotations

import sqlite3
from typing import Tuple

COMPANION_OF_COLUMN = "companion_of"

V86_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("sessions", COMPANION_OF_COLUMN, f"ALTER TABLE sessions ADD COLUMN {COMPANION_OF_COLUMN} INTEGER"),
)

DDL_V86: Tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sessions_companion_of ON sessions(companion_of) "
    "WHERE companion_of IS NOT NULL",
)


def apply_v86(conn: sqlite3.Connection) -> None:
    for table, column, statement in V86_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
    if {row[1] for row in conn.execute("PRAGMA table_info(sessions)")} >= {COMPANION_OF_COLUMN}:
        for statement in DDL_V86:
            conn.execute(statement)

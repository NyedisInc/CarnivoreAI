
from __future__ import annotations

import sqlite3
from typing import Tuple

SHORT_COLUMN = "short_description"
LONG_COLUMN = "long_description"

V74_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("projects", SHORT_COLUMN, f"ALTER TABLE projects ADD COLUMN {SHORT_COLUMN} TEXT"),
    ("sessions", SHORT_COLUMN, f"ALTER TABLE sessions ADD COLUMN {SHORT_COLUMN} TEXT"),
    ("sessions", LONG_COLUMN, f"ALTER TABLE sessions ADD COLUMN {LONG_COLUMN} TEXT"),
)


def apply_v74(conn: sqlite3.Connection) -> None:
    for table, column, statement in V74_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)

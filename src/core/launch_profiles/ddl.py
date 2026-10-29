
from __future__ import annotations

import sqlite3
from typing import Tuple

LAUNCH_RECORD_COLUMN = "launch_record"

DDL_SESSIONS_LAUNCH_RECORD = f"ALTER TABLE sessions ADD COLUMN {LAUNCH_RECORD_COLUMN} TEXT"

V56_COLUMNS: Tuple[Tuple[str, str, str], ...] = (("sessions", LAUNCH_RECORD_COLUMN, DDL_SESSIONS_LAUNCH_RECORD),)

REVERSAL_SQL_V56: Tuple[str, ...] = ()


def apply_v56(conn: sqlite3.Connection) -> None:
    for table, column, statement in V56_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)

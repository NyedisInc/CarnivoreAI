
from __future__ import annotations

import sqlite3
from typing import Tuple

MOVE_STATES: Tuple[str, ...] = ("waiting", "moving", "moved", "failed")

DDL_PACK_MOVE: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS pack_session_moves (
        id                  TEXT NOT NULL,
        role                TEXT NOT NULL DEFAULT 'source' CHECK (role IN ('source', 'target')),
        session_uuid        TEXT NOT NULL,
        claude_session_uuid TEXT,
        source_install_id   TEXT NOT NULL,
        target_install_id   TEXT NOT NULL,
        state               TEXT NOT NULL CHECK (state IN ('waiting', 'moving', 'moved', 'failed')),
        step                TEXT,
        detail_json         TEXT,
        started_at          TEXT NOT NULL,
        finished_at         TEXT,
        error_code          TEXT,
        PRIMARY KEY (id, role)
    )""",
    "CREATE INDEX IF NOT EXISTS pack_session_moves_session ON pack_session_moves(session_uuid, started_at)",
)


def apply_pack_move(conn: sqlite3.Connection) -> None:
    for statement in DDL_PACK_MOVE:
        conn.execute(statement)

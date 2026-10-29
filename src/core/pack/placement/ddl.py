
from __future__ import annotations

import sqlite3
from typing import Tuple

DDL_PACK_PLACEMENT: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS pack_placements (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id            INTEGER,
        session_id          INTEGER,
        workload_json       TEXT NOT NULL,
        chosen_install_id   TEXT,
        mode                TEXT NOT NULL CHECK (mode IN ('stats', 'enhanced', 'fallback', 'explicit')),
        reason              TEXT NOT NULL,
        candidates_json     TEXT NOT NULL,
        created_at          REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS pack_placements_agent ON pack_placements (agent_id)",
    """CREATE TABLE IF NOT EXISTS pack_spawn_queue (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        request_json  TEXT NOT NULL,
        queued_at     REAL NOT NULL,
        attempts      INTEGER NOT NULL DEFAULT 0,
        state         TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'placed', 'cancelled', 'expired')),
        last_reason   TEXT NOT NULL DEFAULT ''
    )""",
)


def apply_pack_placement(conn: sqlite3.Connection) -> None:
    for statement in DDL_PACK_PLACEMENT:
        conn.execute(statement)

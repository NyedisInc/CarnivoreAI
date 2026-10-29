
from __future__ import annotations

import sqlite3
from typing import Tuple

PACK_MACHINES_TABLE = "pack_machines"

DDL_PACK_MACHINES: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS pack_machines (
        install_id          TEXT PRIMARY KEY,
        host_key            TEXT,
        label               TEXT NOT NULL DEFAULT '',
        is_self             INTEGER NOT NULL DEFAULT 0,
        specs_json          TEXT,
        last_snapshot_json  TEXT,
        last_snapshot_at    REAL,
        capabilities_json   TEXT,
        members_json        TEXT,
        updated_at          REAL NOT NULL
    )""",
)


def apply_pack_machines(conn: sqlite3.Connection) -> None:
    for statement in DDL_PACK_MACHINES:
        conn.execute(statement)

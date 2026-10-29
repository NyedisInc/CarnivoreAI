
from __future__ import annotations

import sqlite3
from typing import Tuple

PACK_RELAY_TARGETS_TABLE = "pack_relay_targets"

STATES = ("off", "on", "pushed", "failed", "refused")

DDL_PACK_RELAY: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS pack_relay_targets (
        account_key          TEXT NOT NULL,
        target_install_id    TEXT NOT NULL,
        target_profile       TEXT NOT NULL,
        last_expiry_pushed   INTEGER,
        last_push_at         REAL,
        state                TEXT NOT NULL DEFAULT 'off'
                             CHECK (state IN ('off', 'on', 'pushed', 'failed', 'refused')),
        PRIMARY KEY (account_key, target_install_id)
    )""",
)


def apply_pack_relay(conn: sqlite3.Connection) -> None:
    for statement in DDL_PACK_RELAY:
        conn.execute(statement)


from __future__ import annotations

import sqlite3
from typing import Tuple

USAGE_TABLE = "pack_rollups"
COUNTER_TABLE = "pack_rollup_counters"
STATE_TABLE = "pack_rollup_state"

DDL_V89: Tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {USAGE_TABLE} (
        peer_install_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        hour            INTEGER NOT NULL,
        provider        TEXT,
        agent_kind      TEXT,
        model           TEXT NOT NULL,
        project         TEXT NOT NULL,
        input           INTEGER NOT NULL DEFAULT 0,
        cache_write     INTEGER NOT NULL DEFAULT 0,
        cache_read      INTEGER NOT NULL DEFAULT 0,
        output          INTEGER NOT NULL DEFAULT 0,
        cost_nano       INTEGER NOT NULL DEFAULT 0,
        messages        INTEGER NOT NULL DEFAULT 0,
        priced          INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (peer_install_id, conversation_id, hour, model, project)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {USAGE_TABLE}_hour ON {USAGE_TABLE}(hour)",
    f"""CREATE TABLE IF NOT EXISTS {COUNTER_TABLE} (
        peer_install_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        hour            INTEGER NOT NULL,
        provider        TEXT,
        agent_kind      TEXT,
        model           TEXT NOT NULL,
        project         TEXT NOT NULL,
        counter         TEXT NOT NULL,
        key             TEXT NOT NULL,
        value           INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (peer_install_id, conversation_id, hour, model, project, counter, key)
    ) WITHOUT ROWID""",
    f"CREATE INDEX IF NOT EXISTS {COUNTER_TABLE}_hour ON {COUNTER_TABLE}(hour)",
    f"""CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
        peer_install_id TEXT PRIMARY KEY,
        revision        INTEGER NOT NULL DEFAULT 0,
        scope_digest    TEXT NOT NULL DEFAULT '',
        pulled_at       REAL NOT NULL DEFAULT 0,
        updated_at      REAL NOT NULL DEFAULT 0
    ) WITHOUT ROWID""",
)


def apply_v89(conn: sqlite3.Connection) -> None:
    for statement in DDL_V89:
        conn.execute(statement)


def purge_rows(conn: sqlite3.Connection, peer_install_id: str, *, keep_state: bool = False) -> None:
    for table in (USAGE_TABLE, COUNTER_TABLE):
        conn.execute(f"DELETE FROM {table} WHERE peer_install_id = ?", (peer_install_id,))
    if not keep_state:
        conn.execute(f"DELETE FROM {STATE_TABLE} WHERE peer_install_id = ?", (peer_install_id,))


from __future__ import annotations

import sqlite3
from typing import Tuple

V90_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("crosstalk_messages", "agent_sent", "ALTER TABLE crosstalk_messages ADD COLUMN agent_sent INTEGER"),
    ("crosstalk_messages", "spawn_task", "ALTER TABLE crosstalk_messages ADD COLUMN spawn_task INTEGER"),
    ("crosstalk_messages", "landed_session_id", "ALTER TABLE crosstalk_messages ADD COLUMN landed_session_id TEXT"),
    ("crosstalk_messages", "landed_at", "ALTER TABLE crosstalk_messages ADD COLUMN landed_at REAL"),
    ("crosstalk_messages", "landed_header", "ALTER TABLE crosstalk_messages ADD COLUMN landed_header TEXT"),
    ("crosstalk_messages", "landed_anchor", "ALTER TABLE crosstalk_messages ADD COLUMN landed_anchor TEXT"),
    ("crosstalk_messages", "delivery_path", "ALTER TABLE crosstalk_messages ADD COLUMN delivery_path TEXT"),
)

DDL_V90: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS agent_spawn_links (
        child_id        TEXT PRIMARY KEY,
        child_uuid      TEXT,
        parent_id       TEXT NOT NULL,
        parent_uuid     TEXT,
        parent_kind     TEXT NOT NULL CHECK (parent_kind IN ('session','external')),
        task_message_id TEXT,
        peer_install_id TEXT,
        spawned_at      REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_spawn_links_child_uuid ON agent_spawn_links(child_uuid)",
    "CREATE INDEX IF NOT EXISTS ix_spawn_links_parent_id ON agent_spawn_links(parent_id)",
    "CREATE INDEX IF NOT EXISTS ix_spawn_links_parent_uuid ON agent_spawn_links(parent_uuid)",
    """CREATE TABLE IF NOT EXISTS mcp_events (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id            TEXT NOT NULL,
        started_at         REAL NOT NULL,
        tool               TEXT NOT NULL,
        caller_kind        TEXT NOT NULL CHECK (caller_kind IN ('pane','external')),
        caller_session_id  TEXT,
        caller_tmux        TEXT,
        target_ids         TEXT,
        result_ids         TEXT,
        outcome            TEXT CHECK (outcome IS NULL OR outcome IN ('ok','denied','error')),
        duration_ms        INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS ix_mcp_events_call ON mcp_events(call_id)",
    "CREATE INDEX IF NOT EXISTS ix_mcp_events_time ON mcp_events(started_at)",
    "CREATE INDEX IF NOT EXISTS ix_mcp_events_session ON mcp_events(caller_session_id, started_at)",
)


def apply_v90(conn: sqlite3.Connection) -> None:
    for table, column, statement in V90_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
    for statement in DDL_V90:
        conn.execute(statement)


V95_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("mcp_events", "surface",
     "ALTER TABLE mcp_events ADD COLUMN surface TEXT NOT NULL DEFAULT 'a' CHECK (surface IN ('a','b'))"),
)


def apply_mcp_surface(conn: sqlite3.Connection) -> None:
    for table, column, statement in V95_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)

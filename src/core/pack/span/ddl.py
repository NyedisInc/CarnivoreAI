
from __future__ import annotations

import sqlite3
from typing import Tuple

V82_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("swarm_agents", "host_key", "ALTER TABLE swarm_agents ADD COLUMN host_key TEXT NOT NULL DEFAULT 'local'"),
)

DDL_V82: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS swarm_remote_bodies (
        session_row_id  INTEGER PRIMARY KEY REFERENCES sessions(id),
        home_install_id TEXT NOT NULL,
        home_agent_id   INTEGER NOT NULL,
        project_uid     TEXT NOT NULL,
        rank            TEXT NOT NULL,
        slug            TEXT NOT NULL,
        definition_rev  INTEGER NOT NULL DEFAULT 0,
        mirror_dir      TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        torn_down_at    TEXT
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS swarm_remote_bodies_agent ON swarm_remote_bodies(home_install_id, home_agent_id)",
)


def apply_v82(conn: sqlite3.Connection) -> None:
    for table, column, statement in V82_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
    for statement in DDL_V82:
        conn.execute(statement)

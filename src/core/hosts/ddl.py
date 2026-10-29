
from __future__ import annotations

import sqlite3
from typing import FrozenSet, Tuple

from src.core.hosts.table_columns import table_columns

HOSTS_TABLE = "hosts"
HOST_KEY_COLUMN = "host_key"

LOCAL_HOST_KEY = "local"

LOCAL_HOST_LABEL = "this machine"

HOST_STATE_UP = "up"

PROBE_NEVER = "never"

HOST_INSTANCE_INDEX = "ux_sessions_host_instance"
TRIPLE_INSTANCE_INDEX = "ux_sessions_tmux_instance"

DDL_HOSTS = """
CREATE TABLE IF NOT EXISTS hosts (
  key              TEXT NOT NULL PRIMARY KEY,
  label            TEXT NOT NULL,
  ssh_target       TEXT,
  ssh_port         INTEGER,
  socket           TEXT,
  enabled          INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  tmux_path        TEXT,
  tmux_version     TEXT,
  login_path       TEXT,
  agent_paths_json TEXT,
  login_shell      TEXT,
  machine_id       TEXT,
  remote_carnivore TEXT,
  probe_state      TEXT NOT NULL DEFAULT 'never',
  probe_detail     TEXT,
  probed_at        TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  CHECK (key = 'local' OR (ssh_target IS NOT NULL AND socket IS NOT NULL))
)
"""

INSERT_LOCAL_HOST = (
    "INSERT OR IGNORE INTO hosts (key, label, created_at, updated_at) "
    "VALUES (?, ?, ?, ?)"
)

DDL_SESSIONS_HOST_KEY = (
    "ALTER TABLE sessions ADD COLUMN host_key TEXT NOT NULL DEFAULT 'local'"
)
DDL_PROJECTS_HOST_KEY = (
    "ALTER TABLE projects ADD COLUMN host_key TEXT NOT NULL DEFAULT 'local'"
)

V40_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("sessions", HOST_KEY_COLUMN, DDL_SESSIONS_HOST_KEY),
    ("projects", HOST_KEY_COLUMN, DDL_PROJECTS_HOST_KEY),
)

DDL_SESSIONS_HOST_INSTANCE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sessions_host_instance "
    "ON sessions (host_key, tmux_socket, tmux_name, tmux_created_epoch) "
    "WHERE tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL"
)

DDL_DROP_TRIPLE_INSTANCE_INDEX = "DROP INDEX IF EXISTS ux_sessions_tmux_instance"

DDL_V40: Tuple[str, ...] = (DDL_HOSTS, DDL_SESSIONS_HOST_INSTANCE_INDEX)

_TRIPLE_INSTANCE_INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sessions_tmux_instance "
    "ON sessions (tmux_socket, tmux_name, tmux_created_epoch) "
    "WHERE tmux_name IS NOT NULL AND tmux_created_epoch IS NOT NULL"
)

REVERSAL_SQL_V40: Tuple[str, ...] = (
    "DROP INDEX IF EXISTS ux_sessions_host_instance",
    _TRIPLE_INSTANCE_INDEX_DDL,
    "DROP TABLE IF EXISTS hosts",
)


V96_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (HOSTS_TABLE, "computer_install_id", "ALTER TABLE hosts ADD COLUMN computer_install_id TEXT"),
)


def apply_v96(conn: sqlite3.Connection) -> None:
    for table, column, statement in V96_COLUMNS:
        present = _columns(conn, table)
        if present and column not in present:
            conn.execute(statement)


def _columns(conn: sqlite3.Connection, table: str) -> FrozenSet[str]:
    return table_columns(conn, table)


def apply_v40(conn: sqlite3.Connection, now: str) -> None:
    conn.execute(DDL_HOSTS)
    conn.execute(INSERT_LOCAL_HOST, (LOCAL_HOST_KEY, LOCAL_HOST_LABEL, now, now))
    for table, column, statement in V40_COLUMNS:
        present = _columns(conn, table)
        if present and column not in present:
            conn.execute(statement)
    if HOST_KEY_COLUMN in _columns(conn, "sessions"):
        conn.execute(DDL_SESSIONS_HOST_INSTANCE_INDEX)
        conn.execute(DDL_DROP_TRIPLE_INSTANCE_INDEX)


def host_scope(
    conn: sqlite3.Connection, host_key: str = LOCAL_HOST_KEY, *, column: str = HOST_KEY_COLUMN
) -> Tuple[str, Tuple[str, ...]]:
    if HOST_KEY_COLUMN in _columns(conn, "sessions"):
        return (f" AND {column} = ?", (host_key,))
    if host_key == LOCAL_HOST_KEY:
        return ("", ())
    return (" AND 0", ())

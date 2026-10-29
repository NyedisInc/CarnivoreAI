
from __future__ import annotations

import sqlite3
from typing import Tuple

from src.core.app_alerts import constants as K

DDL_TABLE = f"""
CREATE TABLE IF NOT EXISTS {K.TABLE} (
  id             INTEGER PRIMARY KEY,
  dedupe_key     TEXT NOT NULL,
  source         TEXT NOT NULL,
  severity       TEXT NOT NULL CHECK (severity IN ('info', 'warn', 'error')),
  title_key      TEXT NOT NULL,
  params_json    TEXT NOT NULL DEFAULT '{{}}',
  detail_key     TEXT,
  state          TEXT NOT NULL DEFAULT 'active'
                 CHECK (state IN ('active', 'resolved', 'dismissed', 'snoozed')),
  sticky         INTEGER NOT NULL DEFAULT 0,
  auto_resolve   INTEGER NOT NULL DEFAULT 1,
  first_seen     TEXT NOT NULL,
  last_seen      TEXT NOT NULL,
  count          INTEGER NOT NULL DEFAULT 1,
  resolved_at    TEXT,
  dismissed_at   TEXT,
  snoozed_until  TEXT,
  actions_json   TEXT NOT NULL DEFAULT '[]'
)
"""

DDL_INDEXES: Tuple[str, ...] = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS ux_app_alerts_open_key ON {K.TABLE} (dedupe_key) "
    "WHERE state IN ('active', 'snoozed')",
    f"CREATE INDEX IF NOT EXISTS ix_app_alerts_state ON {K.TABLE} (state, last_seen)",
)

DDL_V50: Tuple[str, ...] = (DDL_TABLE, *DDL_INDEXES)

REVERSAL_SQL_V50: Tuple[str, ...] = (f"DROP TABLE IF EXISTS {K.TABLE}",)


def apply_v50(conn: sqlite3.Connection) -> None:
    for statement in DDL_V50:
        conn.execute(statement)


from __future__ import annotations

import sqlite3
from typing import Tuple

from src.core.transcript_manifest import constants as K

DDL_TABLE = f"""
CREATE TABLE IF NOT EXISTS {K.TABLE} (
  id                     INTEGER PRIMARY KEY,
  path                   TEXT NOT NULL UNIQUE,
  family                 TEXT NOT NULL,
  root                   TEXT NOT NULL,
  source_path            TEXT NOT NULL,
  conversation_id        TEXT,
  kind                   TEXT NOT NULL CHECK (kind IN ('conversation', 'subagent', 'other')),
  size                   INTEGER NOT NULL,
  mtime_ns               INTEGER NOT NULL,
  last_line_uuid         TEXT,
  last_line_offset       INTEGER,
  complete_bytes         INTEGER,
  prev_size              INTEGER,
  prev_last_line_uuid    TEXT,
  prev_last_line_offset  INTEGER,
  prev_complete_bytes    INTEGER,
  dataless               INTEGER NOT NULL DEFAULT 0,
  status                 TEXT NOT NULL DEFAULT 'present'
                         CHECK (status IN ('present', 'grown', 'rewritten', 'gone')),
  first_seen             TEXT NOT NULL,
  last_seen              TEXT NOT NULL,
  changed_at             TEXT NOT NULL,
  gone_at                TEXT
)
"""

DDL_INDEXES: Tuple[str, ...] = (
    f"CREATE INDEX IF NOT EXISTS ix_transcript_files_conversation ON {K.TABLE} (conversation_id, kind)",
    f"CREATE INDEX IF NOT EXISTS ix_transcript_files_status ON {K.TABLE} (status, changed_at)",
)

DDL_V54: Tuple[str, ...] = (DDL_TABLE, *DDL_INDEXES)

REVERSAL_SQL_V54: Tuple[str, ...] = (f"DROP TABLE IF EXISTS {K.TABLE}",)


def apply_v54(conn: sqlite3.Connection) -> None:
    for statement in DDL_V54:
        conn.execute(statement)

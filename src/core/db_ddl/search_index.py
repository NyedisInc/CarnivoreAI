
from __future__ import annotations

import sqlite3
from typing import Tuple

from src.core.db_ddl import tables as K

DDL_DOCS = f"""
CREATE TABLE IF NOT EXISTS {K.DOCS_TABLE} (
  id                 INTEGER PRIMARY KEY,
  conversation_id    TEXT NOT NULL UNIQUE,
  point_id           TEXT NOT NULL,
  transcript_file    TEXT NOT NULL,
  transcript_sha256  TEXT NOT NULL,
  codec              TEXT NOT NULL,
  framed             INTEGER NOT NULL DEFAULT 0,
  packed_bytes       INTEGER NOT NULL DEFAULT 0,
  lines              INTEGER NOT NULL DEFAULT 0,
  rows               INTEGER NOT NULL DEFAULT 0,
  filter_version     TEXT NOT NULL,
  indexed_at         TEXT NOT NULL
)
"""

DDL_ROWS = f"""
CREATE TABLE IF NOT EXISTS {K.ROWS_TABLE} (
  id                 INTEGER PRIMARY KEY,
  doc_id             INTEGER NOT NULL,
  frame_index        INTEGER NOT NULL,
  frame_offset       INTEGER NOT NULL,
  frame_len          INTEGER NOT NULL,
  frame_first_line   INTEGER NOT NULL,
  line               INTEGER NOT NULL,
  kind               TEXT NOT NULL
)
"""

DDL_ROWS_INDEX = f"CREATE INDEX IF NOT EXISTS ix_{K.ROWS_TABLE}_doc ON {K.ROWS_TABLE} (doc_id)"

_FTS_OPTIONS = "content='', tokenize='unicode61 remove_diacritics 2'"

DDL_FTS = f"CREATE VIRTUAL TABLE IF NOT EXISTS {K.FTS_TABLE} USING fts5(body, {_FTS_OPTIONS}, contentless_delete=1)"
DDL_FTS_OLD_SQLITE = f"CREATE VIRTUAL TABLE IF NOT EXISTS {K.FTS_TABLE} USING fts5(body, {_FTS_OPTIONS})"

DDL_V52: Tuple[str, ...] = (DDL_DOCS, DDL_ROWS, DDL_ROWS_INDEX, DDL_FTS)

REVERSAL_SQL_V52: Tuple[str, ...] = (f"DROP TABLE IF EXISTS {K.FTS_TABLE}", f"DROP TABLE IF EXISTS {K.ROWS_TABLE}",
                                     f"DROP TABLE IF EXISTS {K.DOCS_TABLE}")


def fts_supported() -> bool:
    return sqlite3.sqlite_version_info >= K.MIN_SQLITE


def apply_v52(conn: sqlite3.Connection) -> None:
    for statement in (DDL_DOCS, DDL_ROWS, DDL_ROWS_INDEX):
        conn.execute(statement)
    conn.execute(DDL_FTS if fts_supported() else DDL_FTS_OLD_SQLITE)



DDL_LIVE = f"""
CREATE TABLE IF NOT EXISTS {K.LIVE_TABLE} (
  id                  INTEGER PRIMARY KEY,
  conversation_id     TEXT NOT NULL,
  path                TEXT NOT NULL UNIQUE,
  file_kind           TEXT NOT NULL CHECK (file_kind IN ('conversation', 'subagent')),
  family              TEXT NOT NULL,
  base_offset         INTEGER NOT NULL,
  base_line           INTEGER NOT NULL,
  base_point_id       TEXT,
  indexed_offset      INTEGER NOT NULL,
  indexed_lines       INTEGER NOT NULL,
  last_serial         TEXT,
  last_serial_offset  INTEGER,
  rows                INTEGER NOT NULL DEFAULT 0,
  filter_version      TEXT NOT NULL,
  in_scope            INTEGER NOT NULL DEFAULT 1,
  scope               TEXT,
  created_at          TEXT NOT NULL,
  indexed_at          TEXT NOT NULL
)
"""

DDL_LIVE_INDEX = f"CREATE INDEX IF NOT EXISTS ix_{K.LIVE_TABLE}_conversation ON {K.LIVE_TABLE} (conversation_id)"
DDL_ROWS_LIVE_INDEX = (f"CREATE INDEX IF NOT EXISTS ix_{K.ROWS_TABLE}_live ON {K.ROWS_TABLE} ({K.LIVE_ID_COLUMN}) "
                       f"WHERE {K.LIVE_ID_COLUMN} IS NOT NULL")

V55_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (K.ROWS_TABLE, K.LIVE_ID_COLUMN, f"ALTER TABLE {K.ROWS_TABLE} ADD COLUMN {K.LIVE_ID_COLUMN} INTEGER"),
    *((K.DOCS_TABLE, column, f"ALTER TABLE {K.DOCS_TABLE} ADD COLUMN {column} {kind}")
      for column, kind in zip(K.DOC_WATERMARK_COLUMNS, ("INTEGER", "INTEGER", "TEXT", "INTEGER"))),
)

DDL_V55: Tuple[str, ...] = (DDL_LIVE, DDL_LIVE_INDEX, DDL_ROWS_LIVE_INDEX)

REVERSAL_SQL_V55: Tuple[str, ...] = (f"DROP INDEX IF EXISTS ix_{K.ROWS_TABLE}_live", f"DROP TABLE IF EXISTS {K.LIVE_TABLE}")


def apply_v55(conn: sqlite3.Connection) -> None:
    conn.execute(DDL_LIVE)
    conn.execute(DDL_LIVE_INDEX)
    for table, column, statement in V55_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
    conn.execute(DDL_ROWS_LIVE_INDEX)

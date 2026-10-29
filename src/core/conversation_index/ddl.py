
from __future__ import annotations

from typing import Tuple

DDL_TABLE = """
CREATE TABLE IF NOT EXISTS conversation_index (
  id                  INTEGER PRIMARY KEY,
  conversation_id     TEXT NOT NULL UNIQUE,
  agent_family        TEXT NOT NULL DEFAULT 'claude',
  session_uuid        TEXT,
  ended_reason        TEXT,
  parent_conversation_id TEXT,
  project_id          INTEGER,
  project_name        TEXT NOT NULL DEFAULT '',
  session_name        TEXT NOT NULL DEFAULT '',
  working_dir         TEXT,
  wrapper             TEXT,
  account             TEXT,
  started_at          TEXT,
  ended_at            TEXT,
  turns               INTEGER,
  first_prompt        TEXT NOT NULL DEFAULT '',
  files_touched_json  TEXT NOT NULL DEFAULT '[]',
  recent_messages_json TEXT NOT NULL DEFAULT '[]',
  recent_text         TEXT NOT NULL DEFAULT '',
  restore_point_ids_json TEXT NOT NULL DEFAULT '[]',
  summary             TEXT,
  summary_method      TEXT,
  summary_model       TEXT,
  summary_written_at  TEXT,
  summary_state       TEXT NOT NULL DEFAULT 'none'
                      CHECK (summary_state IN ('none', 'queued', 'running', 'done', 'failed')),
  summary_attempts    INTEGER NOT NULL DEFAULT 0,
  summary_next_try_at REAL,
  summary_error       TEXT,
  summary_point_id    TEXT,
  captured_at         TEXT NOT NULL,
  updated_at          TEXT NOT NULL
)
"""

PARENT_INDEX_V46 = "CREATE INDEX IF NOT EXISTS ix_conversation_index_parent ON conversation_index (parent_conversation_id)"

DDL_INDEXES: Tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_conversation_index_session ON conversation_index (session_uuid)",
    "CREATE INDEX IF NOT EXISTS ix_conversation_index_project ON conversation_index (project_id)",
    PARENT_INDEX_V46,
    "CREATE INDEX IF NOT EXISTS ix_conversation_index_queue "
    "ON conversation_index (summary_state, summary_next_try_at)",
    "CREATE INDEX IF NOT EXISTS ix_conversation_index_ended ON conversation_index (ended_at)",
)

DDL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS conversation_index_fts USING fts5(
  summary, recent_text, first_prompt, project_name, session_name,
  content='conversation_index', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2', prefix='2 3'
)
"""

_COLUMNS = "summary, recent_text, first_prompt, project_name, session_name"
_NEW = "new.summary, new.recent_text, new.first_prompt, new.project_name, new.session_name"
_OLD = "old.summary, old.recent_text, old.first_prompt, old.project_name, old.session_name"

DDL_TRIGGERS: Tuple[str, ...] = (
    f"""CREATE TRIGGER IF NOT EXISTS conversation_index_ai AFTER INSERT ON conversation_index BEGIN
  INSERT INTO conversation_index_fts (rowid, {_COLUMNS}) VALUES (new.id, {_NEW});
END""",
    f"""CREATE TRIGGER IF NOT EXISTS conversation_index_ad AFTER DELETE ON conversation_index BEGIN
  INSERT INTO conversation_index_fts (conversation_index_fts, rowid, {_COLUMNS})
    VALUES ('delete', old.id, {_OLD});
END""",
    f"""CREATE TRIGGER IF NOT EXISTS conversation_index_au
  AFTER UPDATE OF {_COLUMNS} ON conversation_index BEGIN
  INSERT INTO conversation_index_fts (conversation_index_fts, rowid, {_COLUMNS})
    VALUES ('delete', old.id, {_OLD});
  INSERT INTO conversation_index_fts (rowid, {_COLUMNS}) VALUES (new.id, {_NEW});
END""",
)

DDL_V46: Tuple[str, ...] = (DDL_TABLE, *DDL_INDEXES, DDL_FTS, *DDL_TRIGGERS)

REVERSAL_SQL_V46: Tuple[str, ...] = (
    "DROP TABLE IF EXISTS conversation_index_fts",
    "DROP TABLE IF EXISTS conversation_index",
)


TABLE_NAME = "conversation_index"
LINK_BASIS_COLUMN = "link_basis"

DDL_V48_ADD_LINK_BASIS = f"ALTER TABLE {TABLE_NAME} ADD COLUMN {LINK_BASIS_COLUMN} TEXT"

V48_COLUMNS: Tuple[Tuple[str, str, str], ...] = ((TABLE_NAME, LINK_BASIS_COLUMN, DDL_V48_ADD_LINK_BASIS),)

REVERSAL_SQL_V48: Tuple[str, ...] = ()


def apply_v48(conn) -> None:
    present = {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE_NAME})")}
    if present and LINK_BASIS_COLUMN not in present:
        conn.execute(DDL_V48_ADD_LINK_BASIS)

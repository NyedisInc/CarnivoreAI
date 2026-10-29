
from __future__ import annotations

from typing import Tuple

LAYOUTS_TABLE = "layouts"
LAYOUT_MEMBERS_TABLE = "layout_members"

SESSION_DELETE_TRIGGER = "tr_sessions_delete_layout_members"

DDL_LAYOUTS = """
CREATE TABLE IF NOT EXISTS layouts (
  id          INTEGER PRIMARY KEY,
  layout_uuid TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  name_fold   TEXT NOT NULL UNIQUE,
  position    INTEGER NOT NULL DEFAULT 0,
  shape       TEXT NOT NULL,
  revision    INTEGER NOT NULL DEFAULT 1,
  source_key  TEXT UNIQUE,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
)
"""

DDL_LAYOUT_MEMBERS = """
CREATE TABLE IF NOT EXISTS layout_members (
  layout_id      INTEGER NOT NULL REFERENCES layouts(id) ON DELETE CASCADE,
  session_row_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  position       INTEGER NOT NULL,
  PRIMARY KEY (layout_id, session_row_id)
)
"""

DDL_LAYOUT_MEMBERS_SESSION_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_layout_members_session "
    "ON layout_members(session_row_id)"
)

# PRAGMA foreign_keys
DDL_SESSION_DELETE_TRIGGER = f"""
CREATE TRIGGER IF NOT EXISTS {SESSION_DELETE_TRIGGER}
BEFORE DELETE ON sessions
BEGIN
  DELETE FROM layouts
   WHERE id IN (SELECT layout_id FROM layout_members WHERE session_row_id = OLD.id)
     AND (SELECT COUNT(*) FROM layout_members m
           WHERE m.layout_id = layouts.id AND m.session_row_id != OLD.id) < 2;
  UPDATE layouts
     SET revision = revision + 1,
         updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
   WHERE id IN (SELECT layout_id FROM layout_members WHERE session_row_id = OLD.id);
  DELETE FROM layout_members WHERE session_row_id = OLD.id;
END
"""

DDL_V34: Tuple[str, ...] = (
    DDL_LAYOUTS,
    DDL_LAYOUT_MEMBERS,
    DDL_LAYOUT_MEMBERS_SESSION_INDEX,
    DDL_SESSION_DELETE_TRIGGER,
)

REVERSAL_SQL_V34: Tuple[str, ...] = (
    f"DROP TRIGGER IF EXISTS {SESSION_DELETE_TRIGGER}",
    "DROP TABLE IF EXISTS layout_members",
    "DROP TABLE IF EXISTS layouts",
)

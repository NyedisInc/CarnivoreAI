
from __future__ import annotations

from typing import Tuple

SESSION_GROUP_STYLES_TABLE = "session_group_styles"

DDL_SESSION_GROUP_STYLES = """
CREATE TABLE IF NOT EXISTS session_group_styles (
  group_id   INTEGER PRIMARY KEY REFERENCES session_groups(id) ON DELETE CASCADE,
  colour     TEXT NOT NULL,
  gradient   TEXT,
  animation  TEXT NOT NULL DEFAULT 'none',
  updated_at TEXT NOT NULL
)
"""

DDL_V33: Tuple[str, ...] = (DDL_SESSION_GROUP_STYLES,)

REVERSAL_SQL_V33: Tuple[str, ...] = ("DROP TABLE IF EXISTS session_group_styles",)

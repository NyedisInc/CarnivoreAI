
from __future__ import annotations

from typing import Tuple

BROWSER_SESSIONS_TABLE = "browser_sessions"

DDL_BROWSER_SESSIONS = """
CREATE TABLE IF NOT EXISTS browser_sessions (
  id         TEXT PRIMARY KEY,
  label      TEXT NOT NULL,
  last_url   TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)
"""

DDL_V32: Tuple[str, ...] = (DDL_BROWSER_SESSIONS,)

REVERSAL_SQL_V32: Tuple[str, ...] = ("DROP TABLE IF EXISTS browser_sessions",)

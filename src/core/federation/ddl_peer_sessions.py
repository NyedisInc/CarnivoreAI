
from __future__ import annotations

from typing import Tuple

DDL_PEER_SESSIONS = """
CREATE TABLE IF NOT EXISTS peer_sessions (
  host_key          TEXT NOT NULL,
  peer_session_uuid TEXT NOT NULL,
  peer_row_id       INTEGER,
  peer_name         TEXT NOT NULL,
  session_id        INTEGER NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
  PRIMARY KEY (host_key, peer_session_uuid)
)
"""

DDL_V45: Tuple[str, ...] = (DDL_PEER_SESSIONS,)

REVERSAL_SQL_V45: Tuple[str, ...] = (
    "DROP TABLE IF EXISTS peer_sessions",
    "DELETE FROM sessions WHERE origin = 'peer'",
    "DELETE FROM projects WHERE root LIKE 'peer://%'",
)


from __future__ import annotations

from typing import Tuple

LAYOUT_BROADCAST_OFF_TABLE = "layout_broadcast_off"

DDL_LAYOUT_BROADCAST_OFF = """
CREATE TABLE IF NOT EXISTS layout_broadcast_off (
  layout_id      INTEGER NOT NULL,
  session_row_id INTEGER NOT NULL,
  updated_at     TEXT NOT NULL,
  PRIMARY KEY (layout_id, session_row_id),
  FOREIGN KEY (layout_id, session_row_id)
    REFERENCES layout_members(layout_id, session_row_id) ON DELETE CASCADE
)
"""

DDL_V37: Tuple[str, ...] = (DDL_LAYOUT_BROADCAST_OFF,)

REVERSAL_SQL_V37: Tuple[str, ...] = ("DROP TABLE IF EXISTS layout_broadcast_off",)

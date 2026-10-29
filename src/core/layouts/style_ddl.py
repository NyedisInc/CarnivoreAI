
from __future__ import annotations

from typing import Tuple

LAYOUT_STYLES_TABLE = "layout_styles"

DDL_LAYOUT_STYLES = """
CREATE TABLE IF NOT EXISTS layout_styles (
  layout_uuid TEXT PRIMARY KEY REFERENCES layouts(layout_uuid) ON DELETE CASCADE,
  colour      TEXT NOT NULL,
  gradient    TEXT,
  animation   TEXT NOT NULL DEFAULT 'none',
  updated_at  TEXT NOT NULL
)
"""

DDL_V36: Tuple[str, ...] = (DDL_LAYOUT_STYLES,)

REVERSAL_SQL_V36: Tuple[str, ...] = ("DROP TABLE IF EXISTS layout_styles",)

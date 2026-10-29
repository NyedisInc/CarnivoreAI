
from __future__ import annotations

from typing import Tuple

ITEM_SETTINGS_TABLE = "item_settings"

DDL_ITEM_SETTINGS = """
CREATE TABLE IF NOT EXISTS item_settings (
  kind           TEXT NOT NULL,
  item_id        TEXT NOT NULL,
  enabled        INTEGER CHECK (enabled IS NULL OR enabled IN (0, 1)),
  schema_version INTEGER,
  values_json    TEXT NOT NULL DEFAULT '{}',
  revision       INTEGER NOT NULL,
  updated_at     TEXT NOT NULL,
  PRIMARY KEY (kind, item_id)
)
"""

DDL_V38: Tuple[str, ...] = (DDL_ITEM_SETTINGS,)

REVERSAL_SQL_V38: Tuple[str, ...] = ("DROP TABLE IF EXISTS item_settings",)

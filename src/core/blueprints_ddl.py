
from __future__ import annotations

from typing import Tuple

BLUEPRINTS_TABLE = "blueprints"

DDL_BLUEPRINTS = """
CREATE TABLE IF NOT EXISTS blueprints (
  id             INTEGER PRIMARY KEY,
  blueprint_uuid TEXT NOT NULL UNIQUE,
  name           TEXT NOT NULL,
  name_fold      TEXT NOT NULL UNIQUE,
  spec           TEXT NOT NULL,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
)
"""

DDL_V35: Tuple[str, ...] = (DDL_BLUEPRINTS,)

REVERSAL_SQL_V35: Tuple[str, ...] = ("DROP TABLE IF EXISTS blueprints",)

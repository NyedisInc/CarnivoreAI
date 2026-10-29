
from __future__ import annotations

from typing import Tuple

INSTALLED_ITEMS_TABLE = "installed_items"
FORKED_COLUMN = "forked"

DDL_V42_ADD_FORKED = (
    f"ALTER TABLE {INSTALLED_ITEMS_TABLE} ADD COLUMN {FORKED_COLUMN} "
    f"INTEGER NOT NULL DEFAULT 0 CHECK ({FORKED_COLUMN} IN (0, 1))"
)

V42_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (INSTALLED_ITEMS_TABLE, FORKED_COLUMN, DDL_V42_ADD_FORKED),
)

REVERSAL_SQL_V42: Tuple[str, ...] = ()


from __future__ import annotations

import sqlite3
from typing import Tuple

from src.core.db import column_exists, table_exists

INSTALLED_ITEMS_TABLE = "installed_items"

PROVENANCE_REPO_COLUMN = "provenance_repo"
PROVENANCE_TAG_COLUMN = "provenance_tag"
COMMIT_SHA_COLUMN = "commit_sha"

DDL_V112_ADD_PROVENANCE_REPO = (
    f"ALTER TABLE {INSTALLED_ITEMS_TABLE} ADD COLUMN {PROVENANCE_REPO_COLUMN} "
    "TEXT NOT NULL DEFAULT ''"
)
DDL_V112_ADD_PROVENANCE_TAG = (
    f"ALTER TABLE {INSTALLED_ITEMS_TABLE} ADD COLUMN {PROVENANCE_TAG_COLUMN} "
    "TEXT NOT NULL DEFAULT ''"
)
DDL_V112_ADD_COMMIT_SHA = (
    f"ALTER TABLE {INSTALLED_ITEMS_TABLE} ADD COLUMN {COMMIT_SHA_COLUMN} "
    "TEXT NOT NULL DEFAULT ''"
)

V112_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    (INSTALLED_ITEMS_TABLE, PROVENANCE_REPO_COLUMN, DDL_V112_ADD_PROVENANCE_REPO),
    (INSTALLED_ITEMS_TABLE, PROVENANCE_TAG_COLUMN, DDL_V112_ADD_PROVENANCE_TAG),
    (INSTALLED_ITEMS_TABLE, COMMIT_SHA_COLUMN, DDL_V112_ADD_COMMIT_SHA),
)

REVERSAL_SQL_V112: Tuple[str, ...] = ()


def apply_v112(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, INSTALLED_ITEMS_TABLE):
        return
    for _table, col, stmt in V112_COLUMNS:
        if not column_exists(conn, INSTALLED_ITEMS_TABLE, col):
            conn.execute(stmt)

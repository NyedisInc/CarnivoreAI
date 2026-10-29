
from __future__ import annotations

from typing import Tuple

from src.core.deepsearch import constants as K
from src.core.db_ddl import search_index as ddl

DDL_ROWS = f"""
CREATE TABLE IF NOT EXISTS {K.ROWS_TABLE} (
  id                 INTEGER PRIMARY KEY,
  doc_id             INTEGER NOT NULL,
  frame_index        INTEGER NOT NULL,
  frame_offset       INTEGER NOT NULL,
  frame_len          INTEGER NOT NULL,
  frame_first_line   INTEGER NOT NULL,
  line               INTEGER NOT NULL,
  kind               TEXT NOT NULL,
  {K.LIVE_ID_COLUMN} INTEGER
)
"""

DDL_META = (f"CREATE TABLE IF NOT EXISTS {K.CACHE_META_TABLE} (id INTEGER PRIMARY KEY CHECK (id = 1), "
            "state TEXT NOT NULL, built_at TEXT)")


DDL_FOLDERS = (f"CREATE TABLE IF NOT EXISTS {K.FOLDERS_TABLE} (live_id INTEGER NOT NULL, folder TEXT NOT NULL, "
               "PRIMARY KEY (live_id, folder)) WITHOUT ROWID")


def statements() -> Tuple[str, ...]:
    return (ddl.DDL_LIVE, ddl.DDL_LIVE_INDEX, DDL_ROWS, ddl.DDL_ROWS_LIVE_INDEX,
            ddl.DDL_FTS if ddl.fts_supported() else ddl.DDL_FTS_OLD_SQLITE, DDL_META, DDL_FOLDERS,
            f"INSERT OR IGNORE INTO {K.CACHE_META_TABLE} (id, state) VALUES (1, '{K.CACHE_BUILDING}')")

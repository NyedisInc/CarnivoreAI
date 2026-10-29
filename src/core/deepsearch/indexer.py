
from __future__ import annotations

import sqlite3
from typing import List, Optional, Tuple

from src.core.deepsearch import constants as K


def write_rows(conn: sqlite3.Connection, doc_id: int, batch: List[Tuple[tuple, str]], live_id: Optional[int] = None) -> None:
    for row, text in batch:
        cursor = conn.execute(
            f"INSERT INTO {K.ROWS_TABLE} (doc_id, frame_index, frame_offset, frame_len, frame_first_line, line, "
            f"kind, {K.LIVE_ID_COLUMN}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (doc_id, *row, live_id))
        conn.execute(f"INSERT INTO {K.FTS_TABLE} (rowid, body) VALUES (?, ?)", (cursor.lastrowid, text))

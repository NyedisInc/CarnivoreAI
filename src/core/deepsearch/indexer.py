
from __future__ import annotations

import sqlite3
from typing import List, Optional, Tuple

from src.core.deepsearch import constants as K


def delete_conversation(conn: sqlite3.Connection, conversation_id: str) -> None:
    from src.core.deepsearch.live import store as live_store

    live_store.delete_main(conn, conversation_id)
    docs = f"SELECT id FROM {K.DOCS_TABLE} WHERE conversation_id = ?"
    conn.execute(f"DELETE FROM {K.FTS_TABLE} WHERE rowid IN "
                 f"(SELECT id FROM {K.ROWS_TABLE} WHERE doc_id IN ({docs}))", (conversation_id,))
    conn.execute(f"DELETE FROM {K.ROWS_TABLE} WHERE doc_id IN ({docs})", (conversation_id,))
    conn.execute(f"DELETE FROM {K.DOCS_TABLE} WHERE conversation_id = ?", (conversation_id,))


def write_rows(conn: sqlite3.Connection, doc_id: int, batch: List[Tuple[tuple, str]], live_id: Optional[int] = None) -> None:
    for row, text in batch:
        cursor = conn.execute(
            f"INSERT INTO {K.ROWS_TABLE} (doc_id, frame_index, frame_offset, frame_len, frame_first_line, line, "
            f"kind, {K.LIVE_ID_COLUMN}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (doc_id, *row, live_id))
        conn.execute(f"INSERT INTO {K.FTS_TABLE} (rowid, body) VALUES (?, ?)", (cursor.lastrowid, text))


from __future__ import annotations

import sqlite3
from typing import Optional


def copy_link(conn: sqlite3.Connection, item_id: int, inbox_id: Optional[int]) -> None:
    if inbox_id is not None:
        conn.execute("UPDATE work_items SET inbox_id = ? WHERE id = ?", (inbox_id, item_id))


def inherit_from_claim(conn: sqlite3.Connection, item_id: int, session_key: str) -> Optional[int]:
    if not session_key:
        return None
    row = conn.execute(
        "SELECT inbox_id FROM work_items WHERE claude_working = 1 AND claude_working_by = ? AND deleted = 0 AND inbox_id IS NOT NULL AND id != ? "
        "ORDER BY seq DESC LIMIT 1", (session_key, item_id)).fetchone()
    if row is None:
        return None
    copy_link(conn, item_id, row["inbox_id"])
    return row["inbox_id"]

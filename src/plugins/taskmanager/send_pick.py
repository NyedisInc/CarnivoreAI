
from __future__ import annotations

import sqlite3
from typing import Dict, Iterable, Optional


REASON_PICKED = "picked"


def picked(conn: sqlite3.Connection, list_key: str) -> Optional[str]:
    row = conn.execute("SELECT target_key FROM work_send_picks WHERE list_key = ?", (list_key,)).fetchone()
    return row[0] if row else None


def set_pick(conn: sqlite3.Connection, list_key: str, target_key: Optional[str]) -> None:
    if not target_key:
        conn.execute("DELETE FROM work_send_picks WHERE list_key = ?", (list_key,))
        return
    conn.execute("INSERT INTO work_send_picks (list_key, target_key) VALUES (?, ?) "
                 "ON CONFLICT(list_key) DO UPDATE SET target_key = excluded.target_key", (list_key, target_key))


def all_picks(conn: sqlite3.Connection, list_keys: Iterable[str]) -> Dict[str, str]:
    keys = list(list_keys)
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    return {r[0]: r[1] for r in conn.execute(f"SELECT list_key, target_key FROM work_send_picks WHERE list_key IN ({marks})", keys)}

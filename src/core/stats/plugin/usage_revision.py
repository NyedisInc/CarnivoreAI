from __future__ import annotations

import sqlite3

KEY = "usage_revision"


def bump(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO stats_meta(key, value) VALUES (?, '1') "
                 "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1", (KEY,))


def read(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM stats_meta WHERE key = ?", (KEY,)).fetchone()
    return int(row[0]) if row else 0


from __future__ import annotations

import sqlite3

from src.core.work import tables

SEQ_KEY = "seq"


def next_seq(conn: sqlite3.Connection) -> int:
    conn.execute(f"UPDATE {tables.META} SET v = v + 1 WHERE k = '{SEQ_KEY}'")
    return cursor(conn)


def cursor(conn: sqlite3.Connection) -> int:
    return int(conn.execute(f"SELECT v FROM {tables.META} WHERE k = '{SEQ_KEY}'").fetchone()[0])

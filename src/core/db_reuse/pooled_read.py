
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from src.core.db_reuse.lent import LentConnection
from src.core.db_reuse.thread_connections import ThreadConnections

POOL_LIMIT = 8


def fresh_for_read(conn: sqlite3.Connection) -> sqlite3.Connection:
    if conn.in_transaction:
        conn.rollback()
    return conn


def is_corrupt(exc: sqlite3.Error) -> bool:
    return isinstance(exc, sqlite3.DatabaseError) and not isinstance(exc, sqlite3.OperationalError)


class ReadPool:

    def __init__(self, opener: Callable[[Path], sqlite3.Connection]) -> None:
        self._threads = ThreadConnections(opener, limit=POOL_LIMIT)

    def lend(self, path: Path) -> LentConnection:
        return LentConnection(fresh_for_read(self._threads.get(path)))

    def forget(self, path: Path) -> None:
        self._threads.discard(path)

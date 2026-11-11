
from __future__ import annotations

import sqlite3


class FailingCommit:

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self) -> "FailingCommit":
        return self

    def __exit__(self, *exc) -> None:
        self._conn.rollback()
        raise sqlite3.OperationalError("database is locked")

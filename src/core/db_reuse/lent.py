
from __future__ import annotations

import sqlite3
from typing import Any


class LentConnection:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def close(self) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def __enter__(self) -> sqlite3.Connection:
        return self._conn.__enter__()

    def __exit__(self, *exc: Any) -> Any:
        return self._conn.__exit__(*exc)

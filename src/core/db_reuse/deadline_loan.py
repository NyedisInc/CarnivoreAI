
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from src.core.db_reuse.pooled_read import is_corrupt


@contextmanager
def discard_on_corrupt(on_corrupt: Callable[[], None]) -> Iterator[None]:
    try:
        yield
    except sqlite3.DatabaseError as exc:
        if is_corrupt(exc):
            on_corrupt()
        raise


class DeadlineLoan:

    def __init__(self, conn: sqlite3.Connection, on_corrupt: Callable[[], None]) -> None:
        self._conn = conn
        self._on_corrupt = on_corrupt

    def __getattr__(self, name: str) -> Any:
        if name in ("_conn", "_on_corrupt"):
            raise AttributeError(name)
        return getattr(self._conn, name)

    def execute(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with discard_on_corrupt(self._on_corrupt):
            return self._conn.execute(*args, **kwargs)

    def close(self) -> None:
        self._conn.set_progress_handler(None, 0)

    def __enter__(self) -> "DeadlineLoan":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

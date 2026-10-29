
from __future__ import annotations

import sqlite3
from typing import Any, Callable, Optional


class LentConnection:

    def __init__(self, conn: sqlite3.Connection, release: Optional[Callable[["LentConnection"], None]] = None) -> None:
        self._conn = conn
        self._release = release

    def close(self) -> None:
        release, self._release = self._release, None
        if release is not None:
            release(self)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

    def __getattr__(self, name: str) -> Any:
        if name in ("_conn", "_release"):
            raise AttributeError(name)
        return getattr(self._conn, name)

    def __enter__(self) -> sqlite3.Connection:
        return self._conn.__enter__()

    def __exit__(self, *exc: Any) -> Any:
        return self._conn.__exit__(*exc)

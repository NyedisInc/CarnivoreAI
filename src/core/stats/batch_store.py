
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Optional


class _SharedConnection:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def close(self) -> None:
        self._conn.set_progress_handler(None, 0)

    def __enter__(self) -> "_SharedConnection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class BatchStore:

    def __init__(self, store: Any) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._revision: Optional[int] = None
        self.scan_memo: dict = {}
        self.scan_metrics: frozenset = frozenset()
        self.fingerprints: dict = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    @property
    def base(self) -> Any:
        return self._store

    def connect(self, *, readonly: bool = False) -> Any:
        if not readonly:
            return self._store.connect(readonly=False)
        with self._lock:
            if self._conn is None:
                self._conn = self._store.connect(readonly=True)
            return _SharedConnection(self._conn)

    def revision(self) -> int:
        with self._lock:
            if self._revision is None:
                if self._conn is None:
                    self._conn = self._store.connect(readonly=True)
                self._revision = int(self._conn.execute("SELECT value FROM stats_meta WHERE key='revision'").fetchone()[0])
            return self._revision

    def release(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

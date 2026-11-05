
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Callable, Optional

from src.core.db_reuse.deadline_loan import DeadlineLoan, discard_on_corrupt
from src.core.stats.plugin import usage_revision
from src.core.stats.store_port import StatsStoreLike


class BatchStore:

    def __init__(self, store: StatsStoreLike) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._revision: Optional[int] = None
        self._usage_revision: Optional[int] = None
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
                self._conn = self._store.connect_read()
            return DeadlineLoan(self._conn, self._drop_broken)

    def revision(self) -> int:
        with self._lock:
            if self._revision is None:
                if self._conn is None:
                    self._conn = self._store.connect_read()
                with discard_on_corrupt(self._discard_conn):
                    self._revision = int(self._conn.execute("SELECT value FROM stats_meta WHERE key='revision'").fetchone()[0])
            return self._revision

    def _discard_conn(self) -> None:
        self._conn = None
        self._store.discard_read()

    def _drop_broken(self) -> None:
        with self._lock:
            self._discard_conn()

    def usage_revision(self) -> int:
        with self._lock:
            if self._usage_revision is None:
                if self._conn is None:
                    self._conn = self._store.connect_read()
                with discard_on_corrupt(self._discard_conn):
                    self._usage_revision = usage_revision.read(self._conn)
            return self._usage_revision

    def release(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.set_progress_handler(None, 0)
                self._conn.close()
                self._conn = None

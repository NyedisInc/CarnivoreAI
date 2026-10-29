
from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Callable, Set

from src.core.work import lists, seq, tx
from src.core.work.storage import WorkStorage, storage_for


class WorkCapability:

    lists = lists

    def __init__(self, state_dir: Path) -> None:
        self._storage = storage_for(state_dir)

    @property
    def storage(self) -> WorkStorage:
        return self._storage

    def open(self) -> None:
        self._storage.ensure_ready()

    def tx(self, touched: Set[str], after_commit: Callable[[str], None]) -> AbstractContextManager[sqlite3.Connection]:
        return tx.write(self._storage.connect, touched, after_commit)

    @staticmethod
    def next_seq(conn: sqlite3.Connection) -> int:
        return seq.next_seq(conn)

    @staticmethod
    def cursor(conn: sqlite3.Connection) -> int:
        return seq.cursor(conn)

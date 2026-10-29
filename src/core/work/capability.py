"""``ctx.work``: the work-store capability a builtin plugin reaches core's store through (issue #1711, split P1).

Permission ``work`` (``src/cplugs/sdk/manifest.py``), BUILTIN TIER ONLY, the ``ctx.swarm`` precedent: a plugin may import only the SDK, so
it cannot call core. The host builds one :class:`WorkCapability` per plugin context over this install's state directory. It hands out the
store's storage (the file, opened and walked by core's ladder), the one write transaction, the one change sequence and the list rules.
The Task Manager keeps its own SQL; what changed in P1 is where the connection and the ladder come from.

Not audited: an activity-log row per store call would write a row for every read (``src/cplugs/host/runtime.py``, ``_UNAUDITED``).
"""

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
        """Bind the state directory; nothing is opened until :meth:`open` or the first connection. Inputs: state_dir (Path)."""
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

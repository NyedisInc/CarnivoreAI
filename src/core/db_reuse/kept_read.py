
from __future__ import annotations

import os
import sqlite3
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Hashable, Iterator, Optional, TypeVar

from src.core.db_reuse import datastore_pool
from src.core.db_reuse.change_cache import HOT_READS, main_file
from src.core.db_reuse.lent import LentConnection
from src.core.db_reuse.pooled_read import fresh_for_read
from src.core.db_reuse.thread_connections import ThreadConnections

T = TypeVar("T")

OPENER_LIMIT = 16

FILES_PER_OPENER = 4


class _Handed(Exception):

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__("connection handed back to the caller instead of kept")
        self.conn = conn


_LOCK = threading.Lock()
_KEPT: "OrderedDict[Hashable, Optional[ThreadConnections]]" = OrderedDict()


def _state_db_path() -> Path:
    from src.config import settings  # noqa: PLC0415
    from src.core.db import db_path_for  # noqa: PLC0415

    return Path(os.path.realpath(db_path_for(settings.get_state_dir())))


def _pool_for(opener: Callable[[], sqlite3.Connection]) -> Optional[ThreadConnections]:
    with _LOCK:
        if opener in _KEPT:
            _KEPT.move_to_end(opener)
            return _KEPT[opener]

        def open_for(path: Path) -> sqlite3.Connection:
            conn = opener()
            if isinstance(conn, LentConnection):
                raise _Handed(conn)
            try:
                real = main_file(conn)
            except BaseException:
                conn.close()
                raise
            if real is None or Path(os.path.realpath(real)) != path:
                raise _Handed(conn)
            return conn

        pool = _KEPT[opener] = ThreadConnections(open_for, limit=FILES_PER_OPENER)
        while len(_KEPT) > OPENER_LIMIT:
            _KEPT.popitem(last=False)
        return pool


@contextmanager
def kept_connection(opener: Callable[[], sqlite3.Connection]) -> Iterator[sqlite3.Connection]:
    pool = _pool_for(opener)
    handed: Optional[sqlite3.Connection] = None
    if pool is None:
        handed = opener()
        conn = handed
    else:
        try:
            conn = LentConnection(fresh_for_read(pool.get(_state_db_path())))
        except _Handed as foreign:
            handed = conn = foreign.conn
            if isinstance(foreign.conn, LentConnection):
                with _LOCK:
                    _KEPT[opener] = None
    try:
        yield conn
    finally:
        if handed is not None:
            handed.close()


def forget_kept(opener: Callable[[], sqlite3.Connection], exc: BaseException) -> None:
    pool = _pool_for(opener)
    if pool is not None:
        pool.discard(_state_db_path())
    from src.config import settings  # noqa: PLC0415
    from src.core.db import db_path_for  # noqa: PLC0415

    datastore_pool.forget_if_broken(db_path_for(settings.get_state_dir()), exc)


def hot_read(opener: Callable[[], sqlite3.Connection], key: Hashable, read: Callable[[sqlite3.Connection], T]) -> T:

    state_path = _state_db_path()

    def load() -> tuple:
        with kept_connection(opener) as conn:
            try:
                value, real = read(conn), main_file(conn)
            except sqlite3.Error as exc:
                forget_kept(opener, exc)
                raise
        return value, (real if real is not None and Path(os.path.realpath(real)) == state_path else None)

    return HOT_READS.fetch_opened((opener, state_path), key, load)

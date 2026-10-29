
from __future__ import annotations

import sqlite3
import threading
import weakref
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator

from src.core.db import connect
from src.core.db_reuse.lent import LentConnection
from src.core.db_reuse.pooled_read import POOL_LIMIT, fresh_for_read, is_corrupt
from src.core.db_reuse.thread_connections import ThreadConnections

_POOL = ThreadConnections(lambda path: connect(path, create=False), limit=POOL_LIMIT)
_BORROWS = threading.local()


class _Loans:

    __slots__ = ("live", "doomed", "owner")

    def __init__(self) -> None:
        self.live: "weakref.WeakSet[LentConnection]" = weakref.WeakSet()
        self.doomed = False
        self.owner = threading.get_ident()


def _loans() -> Dict[str, _Loans]:
    loans = getattr(_BORROWS, "loans", None)
    if loans is None:
        loans = _BORROWS.loans = {}
    return loans


def _end_loan(loans: _Loans, path: Path, conn: sqlite3.Connection, token: LentConnection) -> None:
    loans.live.discard(token)
    if loans.live:
        return
    try:
        if conn.in_transaction:
            conn.rollback()
    except sqlite3.Error:
        pass
    if loans.doomed and threading.get_ident() == loans.owner:
        loans.doomed = False
        _POOL.discard(path)


def lend(path: Path) -> LentConnection:
    key, all_loans = str(path), _loans()
    loans = all_loans.get(key)
    if loans is None:
        loans = all_loans[key] = _Loans()
    nested = bool(loans.live)
    conn = _POOL.held(path) if nested else None
    if conn is None:
        if loans.doomed:
            loans.doomed = False
            _POOL.discard(path)
        conn = _POOL.get(path)
        nested = False
    if not nested:
        fresh_for_read(conn)
        conn.set_progress_handler(None, 0)
    token = LentConnection(conn, lambda t: _end_loan(loans, path, conn, t))
    loans.live.add(token)
    return token


def forget(path: Path) -> None:
    loans = _loans().get(str(path))
    if loans is not None and loans.live:
        loans.doomed = True
        return
    _POOL.discard(path)


def forget_if_broken(path: Path, exc: BaseException) -> None:
    if isinstance(exc, sqlite3.Error) and is_corrupt(exc):
        forget(path)


@contextmanager
def read_only(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    before = conn.execute("PRAGMA query_only").fetchone()[0]
    conn.execute("PRAGMA query_only = ON")
    try:
        yield conn
    finally:
        conn.execute(f"PRAGMA query_only = {1 if before else 0}")

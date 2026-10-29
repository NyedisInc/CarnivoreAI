
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Callable, Iterator, Set


@contextmanager
def write(connect: Callable[[bool], sqlite3.Connection], touched: Set[str],
          after_commit: Callable[[str], None]) -> Iterator[sqlite3.Connection]:
    conn = connect(True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        conn.commit()
    finally:
        conn.close()
    for key in sorted(touched):
        after_commit(key)

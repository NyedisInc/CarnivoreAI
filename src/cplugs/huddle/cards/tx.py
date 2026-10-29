
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Set

from src.cplugs.sdk import work


@contextmanager
def write(store: Any, touched: Set[str]) -> Iterator[sqlite3.Connection]:
    with work.write_tx(store._connect, touched, store._commit_notify) as conn:
        yield conn


def bump(conn: sqlite3.Connection, item_id: int, actor: str, now: Optional[float] = None, *, mark: bool = True) -> int:
    from src.cplugs.huddle.store import TaskManagerStore

    seq = TaskManagerStore._next_seq(conn)
    conn.execute("UPDATE work_items SET revision = revision + 1, seq = ?, updated_at = ? WHERE id = ?",
                 (seq, time.time() if now is None else now, item_id))
    if mark:
        TaskManagerStore._mark(conn, item_id, actor, seq)
    return seq

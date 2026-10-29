
from __future__ import annotations

import sqlite3
from typing import Callable, FrozenSet, Optional

from src.core.db_reuse.kept_read import hot_read

_WAITING = "status IN ('queued','held')"

NOTICE_SOURCES = "'crosstalk','peer'"

EXPIRABLE = f"source IN ({NOTICE_SOURCES},'system')"


def _receivers(conn: sqlite3.Connection) -> FrozenSet[str]:
    return frozenset(r[0] for r in conn.execute(f"SELECT DISTINCT receiver_key FROM crosstalk_messages WHERE {_WAITING}").fetchall())


def _oldest_deadline(conn: sqlite3.Connection) -> Optional[float]:
    row = conn.execute(f"SELECT MIN(expires_at) FROM crosstalk_messages WHERE {_WAITING} AND {EXPIRABLE}").fetchone()
    return row[0] if row else None


def may_have_waiting(opener: Callable[[], sqlite3.Connection], receiver_key: str) -> bool:
    return receiver_key in hot_read(opener, ("crosstalk_waiting_receivers",), _receivers)


def oldest_deadline(opener: Callable[[], sqlite3.Connection]) -> Optional[float]:
    return hot_read(opener, ("crosstalk_oldest_deadline",), _oldest_deadline)

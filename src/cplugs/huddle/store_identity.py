
from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing
from typing import Optional

import structlog

from src.cplugs.sdk import CplugStorage

logger = structlog.get_logger()

KEY = "task_store_id"
BITS = 62


def read(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT v FROM work_meta WHERE k = ?", (KEY,)).fetchone()
    return f"{int(row[0]):016x}" if row is not None else None


def of(storage: CplugStorage) -> Optional[str]:
    try:
        with closing(storage.connect(False)) as conn:
            return read(conn)
    except sqlite3.Error as exc:
        logger.warning("task_manager_store_id_unreadable", error=type(exc).__name__, detail=str(exc)[:200])
        return None


def ensure(conn: sqlite3.Connection) -> str:
    conn.execute("INSERT OR IGNORE INTO work_meta (k, v) VALUES (?, ?)", (KEY, 1 + secrets.randbelow(1 << BITS)))
    found = read(conn)
    if found is None:
        raise sqlite3.DatabaseError("the task store id could not be read back after it was written")
    return found


__all__ = ["BITS", "KEY", "ensure", "of", "read"]

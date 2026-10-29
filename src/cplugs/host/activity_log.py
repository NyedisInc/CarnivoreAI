
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List

import structlog

from src.core.db_reuse.thread_connections import ThreadConnections

logger = structlog.get_logger()

KEEP_ROWS = 500
COALESCE_SECONDS = 30.0
_SCHEMA = """CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, cplug_id TEXT NOT NULL, method TEXT NOT NULL,
  permission TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL, bytes INTEGER NOT NULL, count INTEGER NOT NULL)"""
_INDEX = "CREATE INDEX IF NOT EXISTS activity_by_plugin ON activity(cplug_id, id)"
HOT_BUSY_S = 0.2
BUSY_S = 5.0
_KEYS = ("ts", "method", "permission", "target", "status", "bytes", "count")


def _open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_S)
    try:
        conn.execute(_SCHEMA)
        conn.execute(_INDEX)
    except sqlite3.Error:
        conn.close()
        raise
    return conn


_RECORD_CONNECTIONS = ThreadConnections(_open)


class ActivityLog:

    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(state_dir) / "cplugs" / "activity.db"
        self._clock = clock

    def _connect(self, busy_s: float = BUSY_S) -> sqlite3.Connection:
        conn = _open(self._path)
        conn.execute(f"PRAGMA busy_timeout={int(busy_s * 1000)}")
        return conn

    def record(self, cplug_id: str, *, method: str, permission: str, target: str = "", status: str = "ok", size: int = 0,
               hot: bool = False) -> None:
        now = self._clock()
        method, permission, target, status = method[:80], permission[:300], target[:80], status[:64]
        try:
            conn = _RECORD_CONNECTIONS.get(self._path)
            conn.execute(f"PRAGMA busy_timeout={int((HOT_BUSY_S if hot else BUSY_S) * 1000)}")
            with conn:
                last = conn.execute("SELECT id, ts, method, target, status FROM activity WHERE cplug_id=? ORDER BY id DESC LIMIT 1",
                                    (cplug_id,)).fetchone()
                if last and last[2:] == (method, target, status) and now - last[1] <= COALESCE_SECONDS:
                    conn.execute("UPDATE activity SET ts=?, bytes=bytes+?, count=count+1 WHERE id=?", (now, size, last[0]))
                    return
                row = conn.execute("INSERT INTO activity(ts, cplug_id, method, permission, target, status, bytes, count)"
                                   " VALUES(?,?,?,?,?,?,?,1)", (now, cplug_id, method, permission, target, status, size)).lastrowid
                if row % 50 == 0:
                    conn.execute("DELETE FROM activity WHERE cplug_id=? AND id <= "
                                 "(SELECT id FROM activity WHERE cplug_id=? ORDER BY id DESC LIMIT 1 OFFSET ?)",
                                 (cplug_id, cplug_id, KEEP_ROWS))
        except (sqlite3.Error, OSError) as exc:
            _RECORD_CONNECTIONS.discard(self._path)
            logger.warning("cplug_activity_log_failed", cplug=cplug_id, error_type=type(exc).__name__)

    def recent(self, cplug_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT ts, method, permission, target, status, bytes, count FROM activity "
                                "WHERE cplug_id=? ORDER BY id DESC LIMIT ?", (cplug_id, max(1, min(limit, KEEP_ROWS)))).fetchall()
        return [dict(zip(_KEYS, r)) for r in rows]

    def forget(self, cplug_id: str) -> None:
        if self._path.exists():
            with closing(self._connect()) as conn, conn:
                conn.execute("DELETE FROM activity WHERE cplug_id=?", (cplug_id,))

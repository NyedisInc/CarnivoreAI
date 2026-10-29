
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, List

import structlog

logger = structlog.get_logger()

KEEP_ROWS = 500
_SCHEMA = """CREATE TABLE IF NOT EXISTS egress (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, cplug_id TEXT NOT NULL, host TEXT NOT NULL,
  method TEXT NOT NULL, permission TEXT NOT NULL, status INTEGER NOT NULL, bytes_out INTEGER NOT NULL,
  bytes_in INTEGER NOT NULL, ms INTEGER NOT NULL, outcome TEXT NOT NULL)"""
_INDEX = "CREATE INDEX IF NOT EXISTS egress_by_plugin ON egress(cplug_id, id)"


class EgressLog:

    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(state_dir) / "cplugs" / "egress.db"
        self._clock = clock

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=5)
        conn.execute(_SCHEMA)
        conn.execute(_INDEX)
        return conn

    def record(self, cplug_id: str, *, host: str, method: str, permission: str, status: int, bytes_out: int,
               bytes_in: int, ms: int, outcome: str) -> None:
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("INSERT INTO egress(ts, cplug_id, host, method, permission, status, bytes_out, bytes_in, ms, outcome)"
                             " VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (self._clock(), cplug_id, host[:255], method[:16], permission[:300], status, bytes_out, bytes_in, ms, outcome[:64]))
                conn.execute("DELETE FROM egress WHERE cplug_id=? AND id <= "
                             "(SELECT id FROM egress WHERE cplug_id=? ORDER BY id DESC LIMIT 1 OFFSET ?)",
                             (cplug_id, cplug_id, KEEP_ROWS))
        except (sqlite3.Error, OSError) as exc:
            logger.warning("cplug_egress_log_failed", cplug=cplug_id, error_type=type(exc).__name__)

    def recent(self, cplug_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        if not self._path.exists():
            return []
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT ts, host, method, permission, status, bytes_out, bytes_in, ms, outcome FROM egress "
                                "WHERE cplug_id=? ORDER BY id DESC LIMIT ?", (cplug_id, max(1, min(limit, KEEP_ROWS)))).fetchall()
        keys = ("ts", "host", "method", "permission", "status", "bytes_out", "bytes_in", "ms", "outcome")
        return [dict(zip(keys, r)) for r in rows]

    def forget(self, cplug_id: str) -> None:
        if self._path.exists():
            with closing(self._connect()) as conn, conn:
                conn.execute("DELETE FROM egress WHERE cplug_id=?", (cplug_id,))

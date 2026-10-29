"""The usage store: its own small SQLite file, ``mcp_usage.db`` in the state directory (#1752).

``carnivore.db`` takes no schema change for this. ONE table, ``mcp_tool_daily``: per UTC day, tool, caller kind and
outcome, the number of calls. **NOTHING ELSE IS STORED**: no argument, result, target id, session id or tmux name,
so the file can be kept long and shared without a privacy review. Rows are kept :data:`RETENTION_DAYS` days.

A third table, ``view_reset`` (#1824), holds the ONE reset of the dev tab's counts: when it was pressed (UTC ISO), that UTC day,
and each tool's count for that day at that moment (JSON). It zeroes the VIEW only; the two count tables are never touched by it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

# state directory
DB_FILENAME = "mcp_usage.db"
RETENTION_DAYS = 90
Row = Tuple[str, str, str, str, int]
OldNameRow = Tuple[str, str, str, str, int]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_tool_daily (
    day TEXT NOT NULL,
    tool TEXT NOT NULL,
    caller_kind TEXT NOT NULL,
    outcome TEXT NOT NULL,
    calls INTEGER NOT NULL,
    PRIMARY KEY (day, tool, caller_kind, outcome)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS old_name_daily (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    via TEXT NOT NULL,
    calls INTEGER NOT NULL,
    PRIMARY KEY (day, kind, name, via)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS view_reset (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    reset_at TEXT NOT NULL,
    day TEXT NOT NULL,
    baseline TEXT NOT NULL
);
"""


class UsageStore:

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        if not self._ready:
            with self._lock:
                conn.executescript(_SCHEMA)
                self._ready = True
        return conn

    def latest_day(self) -> Optional[str]:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT MAX(day) FROM mcp_tool_daily").fetchone()[0]

    def replace_from(self, first_day: str, rows: Iterable[Row]) -> int:
        rows = list(rows)
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM mcp_tool_daily WHERE day >= ?", (first_day,))
            conn.executemany("INSERT OR REPLACE INTO mcp_tool_daily (day, tool, caller_kind, outcome, calls) VALUES (?,?,?,?,?)", rows)
        return len(rows)

    def prune(self, today: date, retention_days: int = RETENTION_DAYS) -> int:
        cutoff = (today - timedelta(days=retention_days)).isoformat()
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM old_name_daily WHERE day < ?", (cutoff,))
            return conn.execute("DELETE FROM mcp_tool_daily WHERE day < ?", (cutoff,)).rowcount

    def rows_between(self, first_day: str, last_day: str) -> List[Row]:
        with closing(self._connect()) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT day, tool, caller_kind, outcome, calls FROM mcp_tool_daily WHERE day >= ? AND day <= ?", (first_day, last_day))]

    def last_called_days(self) -> Dict[str, str]:
        with closing(self._connect()) as conn:
            return dict(conn.execute("SELECT tool, MAX(day) FROM mcp_tool_daily GROUP BY tool").fetchall())


    def add_old_names(self, rows: Iterable[OldNameRow]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executemany(
                "INSERT INTO old_name_daily (day, kind, name, via, calls) VALUES (?,?,?,?,?) "
                "ON CONFLICT (day, kind, name, via) DO UPDATE SET calls = calls + excluded.calls", list(rows))

    def old_names_between(self, first_day: str, last_day: str) -> List[OldNameRow]:
        with closing(self._connect()) as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT day, kind, name, via, calls FROM old_name_daily WHERE day >= ? AND day <= ?", (first_day, last_day))]

    def old_names_last_days(self) -> Dict[Tuple[str, str], str]:
        with closing(self._connect()) as conn:
            return {(k, n): d for k, n, d in conn.execute("SELECT kind, name, MAX(day) FROM old_name_daily GROUP BY kind, name")}

    def set_view_reset(self, reset_at: str, day: str, baseline: Dict[str, int]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO view_reset (id, reset_at, day, baseline) VALUES (1, ?, ?, ?)",
                         (reset_at, day, json.dumps(baseline, sort_keys=True)))

    def get_view_reset(self) -> Optional[Tuple[str, str, Dict[str, int]]]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT reset_at, day, baseline FROM view_reset WHERE id = 1").fetchone()
        return None if row is None else (row[0], row[1], json.loads(row[2]))


_default: Optional[UsageStore] = None
_default_lock = threading.Lock()


def get_store() -> UsageStore:
    global _default
    with _default_lock:
        if _default is None:
            from src.config import settings

            _default = UsageStore(Path(settings.get_state_dir()) / DB_FILENAME)
        return _default


def set_store(store: Optional[UsageStore]) -> None:
    global _default
    with _default_lock:
        _default = store


from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Callable, Optional

KEEP_DAYS = 7
_SCHEMA = """CREATE TABLE IF NOT EXISTS usage (
  day TEXT NOT NULL, cplug_id TEXT NOT NULL, feature TEXT NOT NULL,
  calls INTEGER NOT NULL DEFAULT 0, tokens INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, cplug_id, feature))"""


def utc_day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


class AiBudget:

    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(state_dir) / "cplugs" / "ai_budget.db"
        self._clock = clock

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=5, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(_SCHEMA)
        return conn

    def reserve(self, cplug_id: str, feature: str, calls_cap: int, tokens_cap: int) -> Optional[str]:
        now = self._clock()
        day = utc_day(now)
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM usage WHERE day < ?", (utc_day(now - KEEP_DAYS * 86400),))
                row = conn.execute("SELECT calls, tokens FROM usage WHERE day=? AND cplug_id=? AND feature=?",
                                   (day, cplug_id, feature)).fetchone()
                calls, tokens = row if row else (0, 0)
                refusal = "calls_per_day" if calls >= calls_cap else "tokens_per_day" if tokens >= tokens_cap else None
                if refusal is None:
                    conn.execute("INSERT INTO usage(day, cplug_id, feature, calls) VALUES(?,?,?,1) "
                                 "ON CONFLICT(day, cplug_id, feature) DO UPDATE SET calls = calls + 1",
                                 (day, cplug_id, feature))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return refusal

    def note_refusal(self, cplug_id: str, cap: int) -> bool:
        day = utc_day(self._clock())
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO usage(day, cplug_id, feature, calls) VALUES(?,?,'~refusals',1) "
                         "ON CONFLICT(day, cplug_id, feature) DO UPDATE SET calls = calls + 1", (day, cplug_id))
            row = conn.execute("SELECT calls FROM usage WHERE day=? AND cplug_id=? AND feature='~refusals'",
                               (day, cplug_id)).fetchone()
        return row[0] <= cap

    def add_tokens(self, cplug_id: str, feature: str, tokens: int) -> None:
        with closing(self._connect()) as conn:
            conn.execute("INSERT INTO usage(day, cplug_id, feature, tokens) VALUES(?,?,?,?) "
                         "ON CONFLICT(day, cplug_id, feature) DO UPDATE SET tokens = tokens + excluded.tokens",
                         (utc_day(self._clock()), cplug_id, feature, max(0, int(tokens))))

    def today(self, cplug_id: str, feature: str) -> tuple:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT calls, tokens FROM usage WHERE day=? AND cplug_id=? AND feature=?",
                               (utc_day(self._clock()), cplug_id, feature)).fetchone()
        return tuple(row) if row else (0, 0)


from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.core.pipeline import contract as PK
from src.core.stats.store import StatsStore
from src.core.stats_feed.model import WINDOWS, Classes

MINUTE_SPAN_S: int = 86400
MINUTE_ROW_CAP: int = 1500
HOUR_SPAN_S: int = 7 * 86400 + WINDOWS["7d"].bucket_s
HOUR_ROW_CAP: int = 220

_SUMS = "SELECT t, SUM(input), SUM(cache_write), SUM(cache_read), SUM(output) FROM {table} WHERE t >= ? GROUP BY t LIMIT ?"


@dataclass(frozen=True)
class Snapshot:

    revision: int
    enabled: bool
    gaps: List[Tuple[int, Optional[int]]]
    minutes: Dict[int, Classes]
    hours: Dict[int, Classes]
    last_delivery_at: Optional[float]
    db_identity: str


def read_revision(store: StatsStore) -> int:
    return store.revision()


def read_probe(store: StatsStore) -> Tuple[int, str]:
    with store.connect_read() as conn:
        row = conn.execute("SELECT value FROM stats_meta WHERE key='revision'").fetchone()
        if row is None:
            raise sqlite3.DatabaseError("stats.db has no revision row")
        return int(row[0]), _meta(conn, PK.META_CREATED_AT) or ""


def _meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(f"SELECT value FROM {PK.META_TABLE} WHERE key = ?", (key,)).fetchone()
    return None if row is None else row[0]


def _sums(conn: sqlite3.Connection, table: str, since: int, cap: int) -> Dict[int, Classes]:
    return {int(t): Classes(int(a or 0), int(b or 0), int(c or 0), int(d or 0))
            for t, a, b, c, d in conn.execute(_SUMS.format(table=table), (since, cap))}


def read_snapshot(store: StatsStore, now: float) -> Snapshot:
    with store.connect_read() as conn:
        conn.execute("BEGIN")
        try:
            revision_row = conn.execute("SELECT value FROM stats_meta WHERE key='revision'").fetchone()
            settings_row = conn.execute("SELECT enabled FROM stats_settings WHERE singleton=1").fetchone()
            if revision_row is None or settings_row is None:
                raise sqlite3.DatabaseError("stats.db has no revision or settings row")
            revision, enabled = int(revision_row[0]), bool(settings_row[0])
            gaps = [(int(s), None if e is None else int(e)) for s, e in conn.execute(
                "SELECT start_ts, end_ts FROM stats_disabled_spans WHERE end_ts IS NULL OR end_ts > ? LIMIT 200",
                (int(now) - HOUR_SPAN_S,))]
            last = _meta(conn, PK.META_LAST_DELIVERY_AT)
            identity = _meta(conn, PK.META_CREATED_AT) or ""
            minutes = _sums(conn, "usage_minute", int(now // 60) * 60 - MINUTE_SPAN_S, MINUTE_ROW_CAP)
            hours = _sums(conn, "usage_hour", int(now // 3600) * 3600 - HOUR_SPAN_S, HOUR_ROW_CAP)
        finally:
            conn.rollback()
    return Snapshot(revision, enabled, gaps, minutes, hours, float(last) if last else None, identity)

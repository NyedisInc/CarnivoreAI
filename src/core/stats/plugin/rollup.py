
from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from src.core.stats.plugin import revision
from src.core.stats.plugin.schema import COUNTERS, MINUTE_RETENTION_SECONDS

PRUNE_HOURS_PER_WRITE = 6
MINUTE_TABLES = ("usage_minute", "counter_minute", "activity_minute", "coverage_minute", "quota_minute")
SOURCE_TABLES = ("usage_minute", "usage_hour", "counter_minute", "counter_hour")
_COUNTER_IDS = {name: i + 1 for i, name in enumerate(COUNTERS)}
_USAGE_WIDTH = 7


def hour_of(t: int) -> int:
    return t // 3600 * 3600


def dim_id(conn: sqlite3.Connection, table: str, value: str, cache: Dict[Tuple[str, str], int]) -> int:
    hit = cache.get((table, value))
    if hit is not None:
        return hit
    column = "version" if table == "dim_price" else "name"
    conn.execute(f"INSERT OR IGNORE INTO {table} ({column}) VALUES (?)", (value,))
    found = conn.execute(f"SELECT id FROM {table} WHERE {column} = ?", (value,)).fetchone()[0]
    cache[(table, value)] = found
    return found


class Batch:

    def __init__(self, src: int) -> None:
        self.src = src
        self.usage: Dict[Tuple[int, str, str, str], List[int]] = defaultdict(lambda: [0] * _USAGE_WIDTH)
        self.cost_known: Dict[Tuple[int, str, str, str], bool] = {}
        self.counters: Dict[Tuple[int, str, str, str, str], int] = defaultdict(int)

    def add_usage(self, t: int, model: str, project: str, price: str, counts: Iterable[int],
                  cost: "int | None", messages: int) -> None:
        key = (t, model, project, price)
        row = self.usage[key]
        for i, value in enumerate(counts):
            row[i] += value
        if cost is not None:
            row[4] += cost
            row[6] += messages
        self.cost_known[key] = cost is not None
        row[5] += messages

    def add_counter(self, t: int, model: str, project: str, counter: str, key: str, value: int) -> None:
        if value:
            self.counters[(t, model, project, counter, key)] += value

    @property
    def empty(self) -> bool:
        return not self.usage and not self.counters

    def flush(self, conn: sqlite3.Connection, cache: Dict[Tuple[str, str], int]) -> None:
        usage_rows = []
        for (t, model, project, price), v in self.usage.items():
            ids = (dim_id(conn, "dim_model", model, cache), dim_id(conn, "dim_project", project, cache))
            pv = dim_id(conn, "dim_price", price, cache) if price else None
            cost = v[4] if self.cost_known[(t, model, project, price)] else None
            for bucket in (t, hour_of(t)):
                usage_rows.append((bucket, self.src, *ids, v[0], v[1], v[2], v[3], cost, v[5], v[6], pv))
        for table, rows in (("usage_minute", usage_rows[0::2]), ("usage_hour", usage_rows[1::2])):
            conn.executemany(
                f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(t, src, model, project) DO UPDATE "
                "SET input = input + excluded.input, cache_write = cache_write + excluded.cache_write, "
                "cache_read = cache_read + excluded.cache_read, output = output + excluded.output, "
                "cost_nano = CASE WHEN cost_nano IS NULL AND excluded.cost_nano IS NULL THEN NULL "
                "ELSE COALESCE(cost_nano, 0) + COALESCE(excluded.cost_nano, 0) END, "
                "messages = messages + excluded.messages, priced = priced + excluded.priced, "
                "pv = COALESCE(excluded.pv, pv)", rows)
        counter_rows = []
        for (t, model, project, counter, key), value in self.counters.items():
            ids = (dim_id(conn, "dim_model", model, cache), dim_id(conn, "dim_project", project, cache),
                   _COUNTER_IDS[counter], dim_id(conn, "dim_key", key, cache))
            for bucket in (t, hour_of(t)):
                counter_rows.append((bucket, self.src, *ids, value))
        for table, rows in (("counter_minute", counter_rows[0::2]), ("counter_hour", counter_rows[1::2])):
            conn.executemany(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?) ON CONFLICT(t, src, model, project, "
                             "counter, key) DO UPDATE SET value = value + excluded.value", rows)
            if any(r[-1] < 0 for r in rows):
                conn.execute(f"DELETE FROM {table} WHERE src = ? AND value = 0", (self.src,))
        self._mark_revisions(conn)

    def _mark_revisions(self, conn: sqlite3.Connection) -> None:
        row = conn.execute("SELECT conversation_id FROM dim_source WHERE id = ?", (self.src,)).fetchone()
        if row is None:
            return
        hours = {hour_of(key[0]) for key in self.usage} | {hour_of(key[0]) for key in self.counters}
        revision.mark(conn, ((row[0], hour) for hour in hours))


def advance_floor(conn: sqlite3.Connection, now: float | None = None) -> int:
    target = hour_of(int(now if now is not None else time.time()) - MINUTE_RETENTION_SECONDS)
    conn.execute("UPDATE stat_retention SET minute_floor = MAX(minute_floor, ?) WHERE singleton = 1", (target,))
    floor = conn.execute("SELECT minute_floor FROM stat_retention WHERE singleton = 1").fetchone()[0]
    for table in MINUTE_TABLES:
        oldest = conn.execute(f"SELECT MIN(t) FROM {table}").fetchone()[0]
        if oldest is not None and oldest < floor:
            conn.execute(f"DELETE FROM {table} WHERE t < ?",
                         (min(floor, hour_of(oldest) + PRUNE_HOURS_PER_WRITE * 3600),))
    return floor


def drop_source(conn: sqlite3.Connection, src: int) -> None:
    revision.mark_source(conn, src)
    for table in SOURCE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE src = ?", (src,))
    conn.execute("DELETE FROM file_state WHERE src = ?", (src,))
    conn.execute("DELETE FROM dim_source WHERE id = ?", (src,))

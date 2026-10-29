
from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Tuple

from src.core.stats.plugin.rollup import advance_floor, hour_of

ActivityValues = Tuple[float, float, float, int, int, float, float]


def _live_id(conn: sqlite3.Connection, dims: Tuple[str, ...]) -> int:
    conn.execute("INSERT OR IGNORE INTO dim_live (host, provider, conversation_id, project, model, agent_kind) "
                 "VALUES (?,?,?,?,?,?)", dims)
    return conn.execute("SELECT id FROM dim_live WHERE host = ? AND provider = ? AND conversation_id = ? AND "
                        "project = ? AND model = ? AND agent_kind = ?", dims).fetchone()[0]


def add_activity(conn: sqlite3.Connection, minute: int, dims: Tuple[str, ...], values: ActivityValues) -> None:
    live = _live_id(conn, dims)
    for table, bucket in (("activity_minute", minute), ("activity_hour", hour_of(minute))):
        conn.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(t, live) DO UPDATE SET "
                     "observed = observed + excluded.observed, working = working + excluded.working, "
                     "running = running + excluded.running, starts = starts + excluded.starts, "
                     "completions = completions + excluded.completions, waiting = waiting + excluded.waiting, "
                     "subagent = subagent + excluded.subagent", (bucket, live, *values))


def add_coverage(conn: sqlite3.Connection, minute: int, seconds: float) -> None:
    for table, bucket, cap in (("coverage_minute", minute, 60), ("coverage_hour", hour_of(minute), 3600)):
        conn.execute(f"INSERT INTO {table} VALUES (?, ?) ON CONFLICT(t) DO UPDATE SET "
                     f"observed = MIN({cap}, observed + excluded.observed)", (bucket, min(cap, seconds)))


def put_quota(conn: sqlite3.Connection, q: Mapping[str, Any]) -> None:
    for table, bucket in (("quota_minute", q["minute_ts"]), ("quota_hour", hour_of(q["minute_ts"]))):
        conn.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(t, account_id, window, reset_at) "
                     f"DO UPDATE SET utilization = excluded.utilization, fetched_at = excluded.fetched_at, "
                     f"state = excluded.state WHERE excluded.fetched_at > {table}.fetched_at",
                     (bucket, q["account_id"], q["provider"], q["window"], q["reset_at"], q["utilization"],
                      q["fetched_at"], q["state"]))


def retain(conn: sqlite3.Connection, now: float) -> None:
    advance_floor(conn, now)

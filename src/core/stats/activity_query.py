"""Activity metrics read as one SQL GROUP BY per (minute, group) instead of one Python pass per row (#1682, A1).

WHY. ``activity_minutes`` is a view over the minute and hour tables; a 7 day window is about 235k rows, and the
old reader fetched every one of them (each with a correlated lookup of the global observed seconds) and
folded them into cells in Python. That alone spent about 1.65 s of the 2.0 s batch deadline. The metrics a
card shows sum cleanly, so SQLite does the summing and Python folds one row per (minute, group).

ONE SCAN PER BATCH. A Home card asks several activity metrics over the same range and filters (a series, a
summary, then starts, completions, running and the average). :func:`fetch_aggregated` returns the sum of every
plain metric the batch asks for (``store.scan_metrics``) from one scan, and a batch's store memoises it (``store.scan_memo``), so the card pays for the
scan once. The average metrics also read the minute's global observed seconds: they scan grouped by each row's
observed seconds and take the global figure from the coverage table in Python, one dict lookup per minute
(a SQL join against the coverage view cost more than the scan itself).

EXACT, NOT APPROXIMATE. For every metric the fold produces the same cells and coverage as the per-row path
(``queries._fetch`` + ``queries._aggregate``) up to float addition order; ``tests/stats/test_read_path.py``
holds that equality. The per-conversation transform still takes the per-row path because it needs each
row's conversation id.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Callable, NamedTuple

from src.core.stats.plugin.schema import FLOOR_SQL

PLAIN_METRICS = ("observed_seconds", "working_seconds", "running_seconds", "starts", "completions",
                 "waiting_seconds", "subagent_seconds")
_AVERAGE_COLUMN = {"average_working_agents": "working_seconds", "average_running_agents": "running_seconds"}
_DIM_COLUMNS = ("host", "provider", "project", "model", "agent_kind", "conversation_id")
def is_average(metric: str) -> bool:
    return metric in _AVERAGE_COLUMN


class Scan(NamedTuple):
    rows: list
    observed: dict | None


def _memoised(store, key: tuple, compute: Callable[[], object]) -> object:
    memo = getattr(store, "scan_memo", None)
    if memo is None:
        return compute()
    if key not in memo:
        memo[key] = compute()
    return memo[key]


def _conversation_count(filters: dict, start: int, end: int) -> tuple[str, list]:
    clauses = "".join(f" AND {column}=?" for column in _DIM_COLUMNS if column in filters)
    args = [filters[column] for column in _DIM_COLUMNS if column in filters]
    sql = ("SELECT COUNT(DISTINCT conversation_id) FROM dim_live WHERE conversation_id<>''" + clauses +
           f" AND id IN (SELECT live FROM activity_minute WHERE t>=MAX(?,{FLOOR_SQL}) AND t<? "
           f"UNION SELECT live FROM activity_hour WHERE t>=? AND t<MIN(?,{FLOOR_SQL}))")
    return sql, [*args, start, end, start, end]


def _run(store, sql: str, params: list, deadline: float, max_rows: int, limit: type[Exception],
         scalar: bool = False):
    db = store.connect(readonly=True)
    try:
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        cursor = db.execute(sql, params)
        if scalar:
            return cursor.fetchone()[0]
        rows = cursor.fetchall()
        if len(rows) > max_rows:
            raise limit("query exceeds row budget; narrow the range")
        return rows
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            raise limit("query deadline exceeded") from exc
        raise
    finally:
        db.close()


def fetch_aggregated(store, metric: str, where: str, args: list, filters: dict, start: int, end: int,
                     group_by: str | None, deadline: float, max_rows: int, limit: type[Exception],
                     want_conversations: bool) -> tuple["Scan", int]:
    group_column = group_by or "''"
    scan_key = (where, tuple(args), group_by)
    if is_average(metric):
        sql = (f"SELECT minute_ts,{group_column} AS group_value,observed_seconds AS obs,COUNT(*) AS row_count,"
               "SUM(working_seconds) AS m_working_seconds,SUM(running_seconds) AS m_running_seconds "
               f"FROM activity_minutes WHERE {where} "
               f"GROUP BY minute_ts,{group_column},observed_seconds ORDER BY minute_ts LIMIT ?")
        scan = _memoised(store, ("avg", *scan_key), lambda: Scan(
            _run(store, sql, [*args, max_rows + 1], deadline, max_rows, limit),
            {row[0]: row[1] for row in _run(
                store, "SELECT minute_ts,observed_seconds FROM stats_observation_coverage "
                "WHERE minute_ts>=? AND minute_ts<?", [start, end], deadline, max_rows, limit)}))
    else:
        wanted = set(getattr(store, "scan_metrics", ()) or ()) | {metric}
        sums = ",".join(f"SUM({name}) AS m_{name}" for name in PLAIN_METRICS if name in wanted)
        sql = (f"SELECT minute_ts,{group_column} AS group_value,COUNT(*) AS row_count,{sums} "
               f"FROM activity_minutes WHERE {where} GROUP BY minute_ts,{group_column} ORDER BY minute_ts LIMIT ?")
        scan = _memoised(store, ("plain", *scan_key),
                         lambda: Scan(_run(store, sql, [*args, max_rows + 1], deadline, max_rows, limit), None))
    conversations = 0
    if want_conversations:
        count_sql, count_args = _conversation_count(filters, start, end)
        conversations = _memoised(store, ("conversations", count_sql, tuple(count_args)),
                                  lambda: _run(store, count_sql, count_args, deadline, max_rows, limit, scalar=True))
    return scan, conversations


def aggregate(scan: Scan, metric: str, group_by: str | None, bucket_of: Callable[[int], str],
              new_cell: Callable[[], dict], coverage: dict, tick: Callable[[], None]) -> dict[tuple[str, str], dict]:
    average = is_average(metric)
    working = metric == "average_working_agents"
    column = f"m_{_AVERAGE_COLUMN[metric]}" if average else f"m_{metric}"
    observed = scan.observed or {}
    cells: dict[tuple[str, str], dict] = {}
    for index, row in enumerate(scan.rows):
        if index % 1024 == 0:
            tick()
        stamp = row["minute_ts"]
        count = row["row_count"]
        coverage["minute_rows"] += count
        coverage["observed_minutes"].add(stamp)
        if average:
            g = observed.get(stamp, 0)
            known = row["obs"] if working else g
            coverage["known_agent_seconds"] += count * known
            coverage["unknown_agent_seconds"] += count * max(0, g - known)
            if known <= 0:
                coverage["unknown_value_rows"] += count
                continue
        group = str(row["group_value"]) if group_by else "all"
        cell = cells.setdefault((bucket_of(stamp), group), new_cell())
        cell["sum"] += row[column]
        cell["count"] += count
        cell["samples"] += count
        cell["sample_minutes"].add(stamp)
        if average:
            cell["observed_by_minute"][stamp] = max(cell["observed_by_minute"].get(stamp, 0), g)
    return cells

from __future__ import annotations

import os
import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.automations import gates
from src.core.automations import models as m
from src.core.automations.store_schema import closing, run_row

logger = structlog.get_logger()

DAY = 86400.0
REPORT_BUDGET_BYTES = 4 * 1024 * 1024
RECENT_RUNS = 12
MEDIAN_WINDOW = 20
LOCALTIME = "/etc/localtime"
INCLUDE_REPORT = "report"

RUN_TIME = "COALESCE(r.ended_at, r.started_at, r.slot_at, r.created_at)"
_COUNTERS: Dict[str, Tuple[Tuple[str, ...], Optional[int], bool]] = {
    "succeeded_24h": ((m.SUCCEEDED,), 1, False), "failed_24h": ((m.FAILED,), 1, False),
    "succeeded_7d": ((m.SUCCEEDED,), 7, False), "failed_7d": ((m.FAILED,), 7, False),
    "skipped_7d": ((m.SKIPPED,), 7, False), "produced_nothing_7d": ((m.SUCCEEDED,), 7, True),
    "running": ((m.RUNNING, m.CLAIMED), None, False), "waiting_on_you": ((m.WAITING,), None, False)}
COUNTER_IDS = tuple(_COUNTERS)


def counter_clause(counter_id: str, now: float) -> Tuple[str, List[Any]]:
    statuses, days, nothing = _COUNTERS[counter_id]
    sql, args = f"r.status IN ({','.join('?' * len(statuses))})", list(statuses)
    if days is not None:
        sql += f" AND {RUN_TIME} >= ?"
        args.append(now - days * DAY)
    if nothing:
        sql += " AND (r.report_bytes = 0 OR r.output_empty = 1)"
    return f"({sql})", args


def _in(column: str, values: Sequence[str]) -> Tuple[str, List[Any]]:
    return f"{column} IN ({','.join('?' * len(values))})", list(values)


def _filters(now: float, automation_ids: Sequence[str], statuses: Sequence[str], triggers: Sequence[str], hosts: Sequence[str],
             no_host: bool, counters: Sequence[str]) -> Tuple[List[str], List[Any]]:
    clauses: List[str] = []
    args: List[Any] = []
    for column, values in (("r.automation_id", automation_ids), ("r.status", statuses), ("r.trigger", triggers)):
        if values:
            sql, found = _in(column, values)
            clauses.append(sql)
            args += found
    if hosts or no_host:
        parts, found = [], []
        if hosts:
            sql, found = _in("r.host", hosts)
            parts.append(sql)
        if no_host:
            parts.append("r.host IS NULL")
        clauses.append("(" + " OR ".join(parts) + ")")
        args += found
    if counters:
        built = [counter_clause(c, now) for c in counters]
        clauses.append("(" + " OR ".join(sql for sql, _ in built) + ")")
        args += [a for _, found in built for a in found]
    return clauses, args


def _where(clauses: Sequence[str]) -> str:
    return " WHERE " + " AND ".join(clauses) if clauses else ""


def apply_report_budget(rows: List[Dict[str, Any]], budget: int = REPORT_BUDGET_BYTES) -> List[Dict[str, Any]]:
    used, over = 0, False
    for run in rows:
        size = run.get("report_bytes") or 0
        over = over or (size > 0 and used + size > budget)
        run["report_omitted"] = bool(size) and over
        if run["report_omitted"]:
            run.pop("report", None)
        else:
            used += size
    return rows


def feed(store: Any, *, before: str, limit: int, automation_ids: Sequence[str], statuses: Sequence[str], triggers: Sequence[str],
         hosts: Sequence[str], no_host: bool, counters: Sequence[str], with_report: bool) -> Dict[str, Any]:
    now = store._clock()
    clauses, args = _filters(now, automation_ids, statuses, triggers, hosts, no_host, counters)
    page, page_args = list(clauses), list(args)
    if before:
        page.append("r.seq < COALESCE((SELECT seq FROM runs WHERE run_id = ?), 0)")
        page_args.append(before)
    with closing(store._read()) as conn:
        columns = [c[1] for c in conn.execute("PRAGMA table_info(runs)") if c[1] != "report"]
        select = ", ".join(f"r.{c}" for c in columns) + (", r.report" if with_report else ", NULL AS report")
        total = conn.execute(f"SELECT COUNT(*) FROM runs r{_where(clauses)}", args).fetchone()[0]
        found = conn.execute(f"SELECT {select}, a.name AS automation_name FROM runs r JOIN automations a ON a.automation_id = r.automation_id"
                             f"{_where(page)} ORDER BY r.seq DESC LIMIT ?", (*page_args, limit + 1)).fetchall()
    runs = [run_row(r) for r in found]
    more = len(runs) > limit
    runs = runs[:limit]
    if with_report:
        apply_report_budget(runs)
    else:
        for run in runs:
            run.pop("report", None)
    return {"runs": runs, "total": total, "next_before": runs[-1]["run_id"] if more and runs else None}


def counts(store: Any) -> Dict[str, Any]:
    now = store._clock()
    out: Dict[str, Any] = {}
    with closing(store._read()) as conn:
        for counter_id in COUNTER_IDS:
            sql, args = counter_clause(counter_id, now)
            rows = conn.execute(f"SELECT r.automation_id, COUNT(*) FROM runs r WHERE {sql} GROUP BY r.automation_id", args).fetchall()
            out[counter_id] = {"count": sum(r[1] for r in rows), "automation_ids": sorted(r[0] for r in rows)}
        hosts = [r[0] for r in conn.execute("SELECT DISTINCT host FROM runs WHERE host IS NOT NULL ORDER BY host")]
        unrecorded = conn.execute("SELECT EXISTS (SELECT 1 FROM runs WHERE host IS NULL)").fetchone()[0]
        leaving = []
        for statuses, days in (((m.SUCCEEDED, m.FAILED), 1), ((m.SUCCEEDED, m.FAILED, m.SKIPPED), 7)):
            first = conn.execute(f"SELECT MIN({RUN_TIME}) FROM runs r WHERE r.status IN ({','.join('?' * len(statuses))}) "
                                 f"AND {RUN_TIME} > ?", (*statuses, now - days * DAY)).fetchone()[0]
            if first is not None:
                leaving.append(first + days * DAY)
    return {"now": now, "counters": out, "hosts": hosts, "has_unrecorded_host": bool(unrecorded),
            "next_change_at": min(leaving) if leaving else None}


def table_fields(store: Any, automations: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    sql = ("SELECT * FROM (SELECT r.automation_id, r.run_id, r.number, r.status, r.reason, r.trigger, r.attempt, r.slot_at, r.started_at, "
           "r.ended_at, r.skip_count, r.report_bytes, r.output_empty, "
           "ROW_NUMBER() OVER (PARTITION BY r.automation_id ORDER BY r.seq DESC) AS n, "
           "CASE WHEN r.status IN ('succeeded','failed') THEN ROW_NUMBER() OVER (PARTITION BY r.automation_id, "
           "r.status IN ('succeeded','failed') ORDER BY r.seq DESC) END AS settled_n, "
           "CASE WHEN r.status = 'succeeded' AND r.report_bytes > 0 THEN ROW_NUMBER() OVER (PARTITION BY r.automation_id, "
           "(r.status = 'succeeded' AND r.report_bytes > 0) ORDER BY r.seq DESC) END AS reported_n, "
           "COUNT(*) OVER (PARTITION BY r.automation_id) AS run_count, MAX(r.number) OVER (PARTITION BY r.automation_id) AS newest_number "
           "FROM runs r) WHERE n <= ? OR settled_n <= ? OR reported_n = 1")
    with closing(store._read()) as conn:
        rows = conn.execute(sql, (RECENT_RUNS, MEDIAN_WINDOW)).fetchall()
    by_automation: Dict[str, List[Any]] = {}
    for row in rows:
        by_automation.setdefault(row["automation_id"], []).append(row)
    out: Dict[str, Dict[str, Any]] = {}
    for a in automations:
        mine = sorted(by_automation.get(a["automation_id"], []), key=lambda r: r["n"])
        recent = [{**{k: r[k] for k in ("run_id", "number", "status", "reason", "trigger", "attempt", "slot_at", "started_at", "ended_at",
                                        "skip_count", "report_bytes")},
                   "output_empty": None if r["output_empty"] is None else bool(r["output_empty"])} for r in mine if r["n"] <= RECENT_RUNS]
        took = [r["ended_at"] - r["started_at"] for r in mine if r["settled_n"] is not None and r["settled_n"] <= MEDIAN_WINDOW
                and r["status"] == m.SUCCEEDED and r["started_at"] is not None and r["ended_at"] is not None]
        reported = next((r for r in mine if r["reported_n"] == 1), None)
        newest = mine[0] if mine else None
        empty = (reported["output_empty"] == 1) if reported else bool(newest and newest["status"] == m.SUCCEEDED
                                                                       and newest["report_bytes"] == 0)
        out[a["automation_id"]] = {"recent": recent, "median_took_s": statistics.median(took) if took else None,
                                   "newest_output_empty": empty, "run_count": newest["run_count"] if newest else 0,
                                   "newest_number": newest["newest_number"] if newest else None, "spends": gates.spends(a["target"])}
    return out


def zone_name() -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # noqa: PLC0415

    target = os.path.realpath(LOCALTIME)
    name = target.rsplit("/zoneinfo/", 1)[1] if "/zoneinfo/" in target else ""
    try:
        if name:
            ZoneInfo(name)
            return name
    except (ZoneInfoNotFoundError, ValueError, OSError):
        pass
    logger.warning("automations.run_feed.zone_unnamed", link=LOCALTIME)
    return "UTC"

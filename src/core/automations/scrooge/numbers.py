from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.project_writes import list_projects_ordered
from src.core.hosts.identity import is_remote_root
from src.core.stats import config as stats_config
from src.core.stats import queries
from src.core.stats.plugin.extract import project_key
from src.models.stats import QueryRequest

ACTIVE_DAYS = 30
QUERY_WORKERS = 4
NANO = 1_000_000_000
METRICS: Tuple[Tuple[str, str, Dict[str, str]], ...] = (
    ("estimated_cost_nano_usd", "est_cost_usd", {}), ("input_tokens", "input", {}), ("output_tokens", "output", {}),
    ("cache_read_tokens", "cache_read", {}), ("cache_write_5m_tokens", "cache_write_5m", {}),
    ("cache_write_1h_tokens", "cache_write_1h", {}), ("thinking_tokens", "thinking", {}),
    ("compactions", "compactions", {}),
    ("estimated_cost_nano_usd", "subagent_cost_usd", {"agent_kind": "subagent"}),
)
LEVERS: Tuple[Tuple[str, str, str, str], ...] = (
    ("L1", "model tiering", "measured", "cost share by model per project"),
    ("L2", "bounded workers", "partial", "sub-agent cost share only; per-worker call counts are not measured"),
    ("L3", "rule and memory trims", "partial",
     "rule-file size and overlap are measured; the memory index is not measured"),
    ("L4", "skill-listing cut", "not_measured", "no cross-project skill-fire aggregate exists"),
    ("L5", "stop resuming workers", "partial", "proxy only: compactions and cache-write volume"),
    ("L6", "effort discipline", "measured", "thinking tokens relative to output tokens"),
    ("L7", "cache ttl", "measured", "1-hour versus 5-minute cache-write tokens"),
)


def lever_coverage() -> List[Dict[str, str]]:
    return [{"id": i, "title": t, "status": s, "reason": r} for i, t, s, r in LEVERS]


def _request(metric: str, start: datetime, end: datetime, **extra: Any) -> QueryRequest:
    return QueryRequest.model_validate({"metric": metric, "from": start, "to": end, "timezone": "UTC",
                                        "resolution": "day", **extra})


def _usd(nano: Optional[float]) -> Optional[float]:
    return None if nano is None else round(nano / NANO, 6)


def _scale(field: str, value: Optional[float]) -> Optional[float]:
    return _usd(value) if field.endswith("_usd") else value


def scope_projects(conn, *, now: datetime, active_days: int = ACTIVE_DAYS) -> Tuple[List[dict], Dict[str, int]]:
    everything = list_projects_ordered(conn, include_archived=True)
    cutoff = now - timedelta(days=active_days)
    kept: List[dict] = []
    counts = {"excluded_archived": 0, "excluded_idle": 0, "excluded_remote": 0}
    for row in everything:
        if row.get("archived_at"):
            counts["excluded_archived"] += 1
        elif is_remote_root(row["root"]):
            counts["excluded_remote"] += 1
        elif not _worked_since(row.get("work_at"), cutoff):
            counts["excluded_idle"] += 1
        else:
            kept.append(row)
    return kept, counts


def _worked_since(work_at: Optional[str], cutoff: datetime) -> bool:
    if not work_at:
        return False
    try:
        stamp = datetime.fromisoformat(work_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)) >= cutoff


def _ranking(store, metric: str, field: str, filters: Dict[str, str], start: datetime, end: datetime,
             deadline: float) -> Tuple[Dict[str, Any], bool]:
    result = queries.execute(store, _request(metric, start, end, operation="ranking", group_by="project", top_n=10,
                                              filters=filters), deadline)
    values = {item["key"]: _scale(field, item["value"]) for item in result["ranking"] if item["key"] != "other"}
    return values, any(item["key"] == "other" for item in result["ranking"])


def _one(store, metric: str, field: str, filters: Dict[str, str], start: datetime, end: datetime,
         deadline: float) -> Optional[float]:
    result = queries.execute(store, _request(metric, start, end, operation="summary", filters=filters), deadline)
    return _scale(field, result["summary"]["value"])


def _model_mix(store, key: str, start: datetime, end: datetime, deadline: float) -> List[Dict[str, Any]]:
    result = queries.execute(store, _request("estimated_cost_nano_usd", start, end, operation="ranking",
                                             group_by="model", top_n=10, filters={"project": key}), deadline)
    rows = [(item["label"], item["value"]) for item in result["ranking"] if item["value"]]
    total = sum(value for _, value in rows)
    return [{"model": name, "share_pct": round(100.0 * value / total, 1)} for name, value in rows] if total else []


def collect_numbers(store, conn, *, now: Optional[datetime] = None, active_days: int = ACTIVE_DAYS,
                    home: Optional[Path] = None, time_budget_s: float = 60.0) -> Dict[str, Any]:
    stats_config.require_enabled(store)
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=active_days)
    deadline = time.monotonic() + time_budget_s
    home_real = (home or Path.home()).resolve()
    projects, excluded = scope_projects(conn, now=now, active_days=active_days)
    for row in projects:
        row["_key"] = project_key(row["root"])
    with ThreadPoolExecutor(max_workers=QUERY_WORKERS) as pool:
        rank_jobs = {field: pool.submit(_ranking, store, metric, field, extra, start, now, deadline)
                     for metric, field, extra in METRICS}
        total_jobs = {field: pool.submit(_one, store, metric, field, extra, start, now, deadline)
                      for metric, field, extra in METRICS}
        mix_jobs = {row["_key"]: pool.submit(_model_mix, store, row["_key"], start, now, deadline) for row in projects}
        ranked = {field: job.result() for field, job in rank_jobs.items()}
        totals = {field: job.result() for field, job in total_jobs.items()}
        mixes = {key: job.result() for key, job in mix_jobs.items()}
    out: List[Dict[str, Any]] = []
    for row in projects:
        key = row["_key"]
        values: Dict[str, Optional[float]] = {}
        fallback = False
        for metric, field, extra in METRICS:
            by_key, truncated = ranked[field]
            if key in by_key:
                values[field] = by_key[key]
            elif truncated:
                values[field] = _one(store, metric, field, {**extra, "project": key}, start, now, deadline)
                fallback = True
            else:
                values[field] = None
        mix = mixes[key]
        out.append({"project_id": row["id"], "name": row["display_name"], "folder": row["root"],
                    "project_key": key, "home_folder": Path(row["root"]).resolve() == home_real, **values,
                    "model_mix": mix, "root_folder_only": bool(mix) or fallback})
    cost_total = totals["est_cost_usd"]
    for item in out:
        cost = item["est_cost_usd"]
        item["share_pct"] = round(100.0 * cost / cost_total, 1) if cost and cost_total else None
        item["subagent_share_pct"] = _share(item["subagent_cost_usd"], cost)
        item["thinking_share_pct"] = _share(item["thinking"], item["output"])
        item["cache_write_1h_share_pct"] = _share(item["cache_write_1h"], _add(item["cache_write_1h"], item["cache_write_5m"]))
    out.sort(key=lambda item: -(item["est_cost_usd"] or 0))
    return {"window": {"start": start.isoformat(), "end": now.isoformat(), "days": active_days},
            "scope": {"projects": len(out), **excluded},
            "totals": totals, "projects": out, "levers": lever_coverage()}


def _add(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None and b is None else (a or 0) + (b or 0)


def _share(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    return round(100.0 * part / whole, 1) if part is not None and whole else None

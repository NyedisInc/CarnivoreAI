from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import PurePath
from zoneinfo import ZoneInfo

import structlog
from pydantic import ValidationError

from src.core.stats import activity_query, agent_names, answers, pack_scope, project_groups
from src.core.stats.batch_store import BatchStore
from src.core.stats.catalog import METRICS, families_for
from src.core.session_token_usage.model_table import readable_model_name
from src.core.stats.plugin.schema import FLOOR_SQL
from src.core.stats.query_buckets import (
    QueryLimit, all_buckets, bucket_bounds, bucket_of, cell_value, empty_cell, iso_utc, merge_cell, minute_window)
from src.core.stats.project_groups import OTHER_GROUP, OTHER_PUBLIC_KEY, ProjectGroups, other_label
from src.core.provider_ledger import poller
from src.models.stats import QueryRequest, StatsFilters

logger = structlog.get_logger()

MAX_ROWS = 250_000
DEADLINE_SECONDS = 2.0
BATCH_CAP_SECONDS = 6.0
_FILTER_COLUMNS = {
    "host": "host", "provider": "provider", "project": "project",
    "model": "model", "agent_kind": "agent_kind", "conversation_id": "conversation_id",
    "account_id": "account_id", "window": "window", "subagent_type": "subagent_type",
}
_META_DIMENSIONS = ("account_id", "subagent_type")
UNKNOWN = "unknown"
_META_UNRECORDED = {"account_id": "account not recorded", "subagent_type": "no subagent type"}
_USAGE_WITH_META = (
    "(SELECT u.*,COALESCE(m.account_id,'unknown') AS account_id,"
    "COALESCE(m.subagent_type,'unknown') AS subagent_type "
    "FROM minute_usage u LEFT JOIN conversation_meta m ON m.conversation_id=u.conversation_id)")


def _usage_source(filters: StatsFilters, group_by: str | None) -> str:
    used = set(filters.model_dump(exclude_none=True)) | {group_by}
    return _USAGE_WITH_META if used & set(_META_DIMENSIONS) else "minute_usage"


def _allowed_filters(table: str) -> set[str]:
    if table == "quota_minutes":
        return {"provider", "account_id", "window"}
    if table in ("activity_minutes", "minute_counters"):
        return set(_FILTER_COLUMNS) - {"account_id", "window", "subagent_type"}
    return set(_FILTER_COLUMNS) - {"window"}
_REAL_USAGE = "(model!='<synthetic>' OR input_tokens+cache_write_tokens+cache_read_tokens+output_tokens!=0)"
_TOKEN_TOTAL = "input_tokens+cache_write_tokens+cache_read_tokens+output_tokens"


def _resolution(start: int, end: int, choice: str) -> str:
    if choice == "auto":
        for name, seconds in (("minute", 60), ("5minute", 300), ("hour", 3600),
                              ("day", 86400), ("week", 604800), ("month", 2678400),
                              ("year", 31622400)):
            if math.ceil((end - start) / seconds) <= 600:
                return name
        raise QueryLimit("range cannot fit 600 points")
    seconds = {"minute": 60, "5minute": 300, "hour": 3600, "day": 86400,
               "week": 604800, "month": 2678400, "year": 31622400}[choice]
    if math.ceil((end - start) / seconds) > (650 if choice in ("month", "year") else 600):
        raise QueryLimit("resolution exceeds 600 points")
    return choice


def _project_labels(groups: ProjectGroups, members: int = 0) -> dict[str, str]:
    return {**groups.labels, OTHER_GROUP: other_label(members)}


def _regroup(cells: dict, groups: ProjectGroups) -> tuple[dict, dict[str, float]]:
    folded: dict = {}
    sums: dict[str, float] = defaultdict(float)
    for (bucket, raw), cell in cells.items():
        group = groups.group_of(raw) if raw else OTHER_GROUP
        merge_cell(folded.setdefault((bucket, group), empty_cell()), cell)
        sums[raw or ""] += cell["sum"]
    return folded, sums


def _account_labels() -> dict[str, str]:
    return {account.id: account.name for account in poller.snapshot().accounts if account.name}


def _fold_subagents(cells: dict) -> dict:
    folded: dict = {}
    for (bucket, raw), cell in cells.items():
        merge_cell(folded.setdefault((bucket, agent_names.root_of(raw)), empty_cell()), cell)
    return folded


OTHER_BUCKET = "@other"


def _public_dimension(name: str | None, raw: str | None,
                      project_labels: dict[str, str] | None = None,
                      account_labels: dict[str, str] | None = None,
                      agent_labels: dict[str, str] | None = None) -> tuple[str, str, str | None]:
    if name == "project" and raw == OTHER_GROUP:
        return OTHER_PUBLIC_KEY, (project_labels or {}).get(OTHER_GROUP, other_label(0)), None
    if name == "project" and raw and re.fullmatch(r"[0-9a-f]{24}", raw):
        return raw, (project_labels or {}).get(raw, other_label(1)), raw
    if raw == UNKNOWN and name in _META_DIMENSIONS:
        return UNKNOWN, _META_UNRECORDED[name], UNKNOWN
    if name == "account_id" and raw:
        label = (account_labels or {}).get(raw, "account no longer configured")
        if "/" in label or "\\" in label:
            label = PurePath(label.replace("\\", "/")).name
        return raw, label, raw
    if name == "project" and raw and ("/" in raw or "\\" in raw):
        return "project:" + hashlib.sha256(raw.encode()).hexdigest()[:16], PurePath(raw).name or other_label(1), None
    if raw == OTHER_BUCKET:
        return "other", "Other", None
    if raw == "other" and name != "conversation_id":
        return "other:value", "other", raw
    if name == "conversation_id" and raw:
        label = raw[:36] if agent_labels is None else agent_labels.get(raw, agent_names.UNNAMED)
        return "conversation:" + hashlib.sha256(raw.encode()).hexdigest()[:16], label, raw
    if name == "model" and raw:
        return raw, readable_model_name(raw) or raw, raw
    label = raw or "Unknown"
    return label, label, raw


def _where(table: str, filters: StatsFilters, start: int, end: int,
           counter: str | None = None) -> tuple[str, list]:
    parts = ["minute_ts>=?", "minute_ts<?"]
    if table == "minute_usage":
        parts.append(_REAL_USAGE)
    args: list = [start, end]
    if table == "minute_counters":
        parts.append("counter=?")
        args.append(counter)
    fields = filters.model_dump(exclude_none=True)
    allowed = _allowed_filters(table)
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"{key} is unavailable for {table}")
        parts.append(f"{_FILTER_COLUMNS[key]}=?")
        args.append(value)
    return " AND ".join(parts), args


def _fetch(store, table: str, filters: StatsFilters, start: int, end: int,
           group_by: str | None, deadline: float | None = None, counter: str | None = None,
           arm: pack_scope.Arm | None = None):
    if table == "minute_counters":
        cols = "minute_ts,host,provider,conversation_id,project,model,agent_kind,key,value AS counter_value"
    elif table == "quota_minutes":
        cols = "minute_ts,provider,account_id,window,utilization,fetched_at,state"
    elif table == "activity_minutes":
        cols = ("minute_ts,host,provider,conversation_id,project,model,agent_kind,"
                "observed_seconds,working_seconds,running_seconds,starts,completions,"
                "waiting_seconds,subagent_seconds,"
                "COALESCE((SELECT observed_seconds FROM stats_observation_coverage c "
                "WHERE c.minute_ts=activity_minutes.minute_ts),0) AS global_observed_seconds")
    else:
        cols = ("minute_ts,host,provider,conversation_id,project,model,agent_kind,"
                "input_tokens,cache_write_tokens,cache_read_tokens,output_tokens,"
                "estimated_cost_nano_usd,price_version,usage_count,"
                "priced_usage_count,unpriced_usage_count,quality")
    source = table
    if table == "minute_usage":
        source = _usage_source(filters, group_by)
        if source != table:
            cols += ",account_id,subagent_type"
    source = arm.source if arm and arm.source else source
    where, args = _where(table, filters, start, end, counter)
    if arm:
        skip, skip_args = arm.where()
        where, args = where + skip, args + skip_args
    deadline = deadline or time.monotonic() + DEADLINE_SECONDS
    db = arm.connect(store) if arm else store.connect(readonly=True)
    try:
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        cursor = db.execute(f"SELECT {cols} FROM {source} WHERE {where} ORDER BY minute_ts LIMIT ?", (*args, MAX_ROWS + 1))
        rows = cursor.fetchall()
        if len(rows) > MAX_ROWS:
            raise QueryLimit("query exceeds row budget; narrow the range")
        return rows
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            raise QueryLimit("query deadline exceeded") from exc
        raise
    finally:
        db.close()


def _fetch_usage_aggregated(store, metric: str, filters: StatsFilters,
                            start: int, end: int, group_by: str | None,
                            deadline: float, arm: pack_scope.Arm | None = None) -> tuple[list, int | set]:
    expression = _TOKEN_TOTAL if metric == "total_tokens" else metric
    group_column = group_by or "''"
    where, args = _where("minute_usage", filters, start, end)
    source = _usage_source(filters, group_by)
    if arm:
        skip, skip_args = arm.where()
        where, args, source = where + skip, args + skip_args, arm.source or source
    db = arm.connect(store) if arm else store.connect(readonly=True)
    try:
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        rows = db.execute(
            f"SELECT minute_ts,{group_column} AS group_value,SUM({expression}) AS metric_value,"
            "COUNT(*) AS row_count,SUM(usage_count) AS usage_count,"
            "SUM(priced_usage_count) AS priced_usage_count,"
            "SUM(unpriced_usage_count) AS unpriced_usage_count,"
            f"SUM(CASE WHEN priced_usage_count>0 AND unpriced_usage_count=0 THEN {_TOKEN_TOTAL} ELSE 0 END) AS priced_token_total,"
            f"SUM(CASE WHEN unpriced_usage_count>0 AND priced_usage_count=0 THEN {_TOKEN_TOTAL} ELSE 0 END) AS unpriced_token_total,"
            f"SUM(CASE WHEN priced_usage_count>0 AND unpriced_usage_count>0 THEN {_TOKEN_TOTAL} ELSE 0 END) AS mixed_price_token_total,"
            "SUM(CASE WHEN quality!='ok' THEN 1 ELSE 0 END) AS quality_count,"
            "SUM(CASE WHEN estimated_cost_nano_usd IS NULL THEN 1 ELSE 0 END) AS unknown_count,"
            "GROUP_CONCAT(DISTINCT price_version) AS price_versions "
            f"FROM {source} WHERE {where} GROUP BY minute_ts,{group_column} "
            "ORDER BY minute_ts LIMIT ?",
            (*args, MAX_ROWS + 1),
        ).fetchall()
        if len(rows) > MAX_ROWS:
            raise QueryLimit("query exceeds row budget; narrow the range")
        if arm:
            return rows, {r[0] for r in db.execute(f"SELECT DISTINCT conversation_id FROM {source} WHERE {where}", args)}
        conversations = db.execute(
            f"SELECT COUNT(DISTINCT conversation_id) FROM {source} WHERE {where}", args,
        ).fetchone()[0]
        return rows, conversations
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            raise QueryLimit("query deadline exceeded") from exc
        raise
    finally:
        db.close()


def _value(row, metric: str) -> float | int | None:
    if "metric_value" in row.keys():
        return row["metric_value"]
    if "counter_value" in row.keys():
        return row["counter_value"]
    if metric == "total_tokens":
        return sum(row[k] for k in ("input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens"))
    if metric == "average_working_agents":
        return row["working_seconds"]
    if metric == "average_running_agents":
        return row["running_seconds"]
    if metric == "quota_utilization":
        return row["utilization"]
    return row[metric]


def _new_coverage() -> dict:
    return {"minute_rows": 0, "unknown_value_rows": 0, "quality_rows": 0,
            "observed_minutes": set(), "price_versions": set(),
            "known_agent_seconds": 0.0, "unknown_agent_seconds": 0.0,
            "priced_usage_count": 0, "unpriced_usage_count": 0,
            "priced_token_total": 0, "unpriced_token_total": 0,
            "mixed_price_token_total": 0}


def _aggregate_activity(rows, metric: str, resolution: str, zone: ZoneInfo,
                        group_by: str | None, deadline: float) -> tuple[dict, dict]:
    coverage = _new_coverage()

    def tick() -> None:
        if time.monotonic() > deadline:
            raise QueryLimit("query deadline exceeded")

    cells = activity_query.aggregate(rows, metric, group_by, lambda stamp: bucket_of(stamp, resolution, zone),
                                     empty_cell, coverage, tick)
    return cells, coverage


def _aggregate(rows, metric: str, resolution: str, zone: ZoneInfo,
               group_by: str | None, deadline: float) -> tuple[dict, dict]:
    cells: dict[tuple[str, str], dict] = {}
    coverage = _new_coverage()
    for index, row in enumerate(rows):
        if index % 1024 == 0 and time.monotonic() > deadline:
            raise QueryLimit("query deadline exceeded")
        stamp = row["minute_ts"]
        aggregated = "metric_value" in row.keys()
        coverage["minute_rows"] += row["row_count"] if aggregated else 1
        coverage["observed_minutes"].add(stamp)
        if aggregated:
            coverage["quality_rows"] += row["quality_count"]
        elif "quality" in row.keys() and row["quality"] != "ok":
            coverage["quality_rows"] += 1
        if aggregated and row["price_versions"]:
            coverage["price_versions"].update(row["price_versions"].split(","))
        if "price_version" in row.keys() and row["price_version"]:
            coverage["price_versions"].update(row["price_version"].split(","))
        value = _value(row, metric)
        group = str(row["group_value"]) if aggregated and group_by else (
            str(row[group_by]) if group_by else "all")
        key = (bucket_of(stamp, resolution, zone), group)
        if metric == "estimated_cost_nano_usd":
            coverage["priced_usage_count"] += row["priced_usage_count"]
            coverage["unpriced_usage_count"] += row["unpriced_usage_count"]
            if aggregated:
                for name in ("priced_token_total", "unpriced_token_total", "mixed_price_token_total"):
                    coverage[name] += row[name]
            else:
                tokens = sum(row[name] for name in (
                    "input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens"))
                category = ("mixed_price_token_total" if row["priced_usage_count"] and row["unpriced_usage_count"]
                            else "priced_token_total" if row["priced_usage_count"]
                            else "unpriced_token_total" if row["unpriced_usage_count"] else None)
                if category:
                    coverage[category] += tokens
            cells.setdefault(key, empty_cell())["samples"] += (
                row["row_count"] if aggregated else 1)
            if aggregated:
                coverage["unknown_value_rows"] += row["unknown_count"]
            if row["unpriced_usage_count"]:
                cells.setdefault(key, empty_cell())["unknown"] += row["unpriced_usage_count"]
        if metric in ("average_working_agents", "average_running_agents"):
            global_seconds = row["global_observed_seconds"]
            known_seconds = (row["observed_seconds"] if metric == "average_working_agents"
                             else global_seconds)
            coverage["known_agent_seconds"] += known_seconds
            coverage["unknown_agent_seconds"] += max(0, global_seconds - known_seconds)
        if (value is None or (metric == "quota_utilization" and row["state"] != "ok")
                or (metric == "average_working_agents" and row["observed_seconds"] <= 0)
                or (metric == "average_running_agents" and row["global_observed_seconds"] <= 0)):
            if not aggregated:
                coverage["unknown_value_rows"] += 1
            continue
        cell = cells.setdefault(key, empty_cell())
        cell["sum"] += value
        cell["count"] += row["row_count"] if aggregated else 1
        if metric != "estimated_cost_nano_usd":
            cell["samples"] += row["row_count"] if aggregated else 1
        cell["sample_minutes"].add(stamp)
        if "conversation_id" in row.keys() and row["conversation_id"]:
            cell["conversations"].add(row["conversation_id"])
        if "observed_seconds" in row.keys():
            current = cell["observed_by_minute"].get(stamp, 0)
            denominator = row["global_observed_seconds"]
            cell["observed_by_minute"][stamp] = max(current, denominator)
    return cells, coverage


def _finished_coverage(data: dict, start: int, end: int) -> dict:
    return {
        "minute_rows": data["minute_rows"],
        "observed_minutes": len(data["observed_minutes"]),
        "range_minutes": (end - start) // 60,
        "unknown_value_rows": data["unknown_value_rows"],
        "priced_usage_count": data["priced_usage_count"],
        "unpriced_usage_count": data["unpriced_usage_count"],
        "priced_token_total": data["priced_token_total"],
        "unpriced_token_total": data["unpriced_token_total"],
        "mixed_price_token_total": data["mixed_price_token_total"],
        "quality_rows": data["quality_rows"],
        "known_agent_seconds": data["known_agent_seconds"],
        "unknown_agent_seconds": data["unknown_agent_seconds"],
        "partial": bool(data["unknown_value_rows"] or data["quality_rows"] or
                        data["unpriced_usage_count"] or data["unknown_agent_seconds"]),
        "price_versions": sorted(data["price_versions"]),
    }


def _transformed(value: float | int | None, cell: dict, request: QueryRequest,
                 resolution: str, bucket: str, zone: ZoneInfo,
                 span_start: int, span_end: int) -> float | int | None:
    if value is None:
        return None
    if request.transform == "rate":
        bucket_start, bucket_end = bucket_bounds(bucket, resolution, zone)
        return value / max(1, min(bucket_end, span_end) - max(bucket_start, span_start))
    if request.transform == "per_conversation":
        count = len(cell["conversations"])
        return value / count if count else None
    return value


def _price_provenance(store, versions: list[str]) -> list[dict]:
    if not versions:
        return []
    db = store.connect(readonly=True)
    try:
        placeholders = ",".join("?" for _ in versions)
        rows = db.execute(
            f"SELECT version,source,source_date FROM price_versions WHERE version IN ({placeholders})",
            versions,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def _read_span(store, request: QueryRequest, table: str, start: int, end: int, deadline: float,
               arm: pack_scope.Arm | None) -> tuple[list, int | set]:
    if table == "minute_usage" and request.transform != "per_conversation":
        return _fetch_usage_aggregated(store, request.metric, request.filters, start, end, request.group_by, deadline, arm)
    if table == "activity_minutes" and request.transform != "per_conversation":
        where, args = _where(table, request.filters, start, end)
        return activity_query.fetch_aggregated(
            store, request.metric, where, args, request.filters.model_dump(exclude_none=True), start, end,
            request.group_by, deadline, MAX_ROWS, QueryLimit, request.operation in ("summary", "comparison"))
    rows = _fetch(store, table, request.filters, start, end, request.group_by, deadline, request.metric, arm)
    found = {row["conversation_id"] for row in rows if "conversation_id" in row.keys() and row["conversation_id"]}
    return rows, (found if arm else len(found))


def _pack_query(store, request: QueryRequest, table: str) -> pack_scope.PackQuery | None:
    if request.scope != "pack" or table not in pack_scope.PACK_TABLES:
        return None
    view = store if isinstance(store, BatchStore) else BatchStore(store)
    try:
        return pack_scope.for_request(store, view, request, table)
    finally:
        if view is not store:
            view.release()


def execute(store, request: QueryRequest, deadline: float | None = None) -> dict:
    deadline = deadline if deadline is not None else time.monotonic() + DEADLINE_SECONDS
    unit, table = METRICS[request.metric]
    if table in ("activity_minutes", "minute_counters") and request.group_by in (
            "account_id", "window", "subagent_type"):
        raise ValueError(f"{request.group_by} grouping is unavailable for {request.metric}")
    if request.group_by == "key" and table != "minute_counters":
        raise ValueError(f"key grouping is unavailable for {request.metric}")
    groups = project_groups.groups_for(store) if request.group_by == "project" else None
    project_labels = _project_labels(groups) if groups is not None else None
    other_members: dict[str, float] = defaultdict(float)
    account_labels = _account_labels() if request.group_by == "account_id" else None
    agent_labels = agent_names.names_for(store) if request.group_by == "conversation_id" else None
    start, end = minute_window(request)
    resolution = _resolution(start, end, request.resolution)
    zone = ZoneInfo(request.timezone)
    pack = _pack_query(store, request, table)
    spans = [(start, end)]
    if request.comparison:
        compare_start, compare_end = minute_window(request.comparison)
        if compare_end - compare_start != end - start:
            raise ValueError("comparison ranges must have equal duration")
        spans.append((compare_start, compare_end))
    prepared = []
    for span_start, span_end in spans:
        if time.monotonic() > deadline:
            raise QueryLimit("query deadline exceeded")
        fast_activity = table == "activity_minutes" and request.transform != "per_conversation"
        rows, conversation_count = _read_span(store, request, table, span_start, span_end, deadline,
                                              pack.arms[0] if pack else None)
        for arm in (pack.arms[1:] if pack else ()):
            more, more_conversations = _read_span(store, request, table, span_start, span_end, deadline, arm)
            rows, conversation_count = rows + more, conversation_count | more_conversations
        if pack:
            conversation_count = len(conversation_count)
        aggregate = _aggregate_activity if fast_activity else _aggregate
        cells, coverage = aggregate(rows, request.metric, resolution, zone, request.group_by, deadline)
        if groups is not None:
            cells, raw_sums = _regroup(cells, groups)
            for raw, value in raw_sums.items():
                if groups.group_of(raw) == OTHER_GROUP:
                    other_members[raw] += value
        if request.group_by == "conversation_id":
            cells = _fold_subagents(cells)
        buckets = all_buckets(span_start, span_end, resolution, zone)
        totals: dict[str, dict] = defaultdict(empty_cell)
        for (_, group), cell in cells.items():
            merge_cell(totals[group], cell)
        prepared.append((span_start, span_end, rows, cells, coverage, buckets,
                         totals, conversation_count))
    primary_totals = prepared[0][6]
    primary_order = sorted(primary_totals, key=lambda group: (
        cell_value(primary_totals[group], request.metric, resolution) is None,
        -(cell_value(primary_totals[group], request.metric, resolution) or 0), group))
    primary_selected = primary_order[:request.top_n] if request.group_by else ["all"]
    has_other = request.group_by and any(
        group not in primary_selected for item in prepared for group in item[6])
    selected = primary_selected + ([OTHER_BUCKET] if has_other else [])
    if len(selected) * len(spans) > 12:
        raise QueryLimit("more than 12 expanded series")
    other_detail = None
    if groups is not None and other_members:
        ordered_members = sorted(other_members, key=lambda raw: (-other_members[raw], raw))
        other_detail = groups.other_detail(ordered_members)
        project_labels = _project_labels(groups, other_detail["count"])
    output: list[dict] = []
    all_coverage: list[dict] = []
    for span_start, span_end, rows, cells, coverage, buckets, totals, conversation_count in prepared:
        if time.monotonic() > deadline:
            raise QueryLimit("query deadline exceeded")
        all_coverage.append(_finished_coverage(coverage, span_start, span_end))
        series = []
        for group in selected:
            if time.monotonic() > deadline:
                raise QueryLimit("query deadline exceeded")
            public_key, label, filter_value = _public_dimension(request.group_by, group, project_labels, account_labels, agent_labels)
            points = []
            source_cells = cells
            if group == OTHER_BUCKET:
                source_cells = {}
                for (bucket, cell_group), cell in cells.items():
                    if cell_group not in primary_selected:
                        merge_cell(source_cells.setdefault((bucket, OTHER_BUCKET), empty_cell()), cell)
            for index, bucket in enumerate(buckets):
                if index % 64 == 0 and time.monotonic() > deadline:
                    raise QueryLimit("query deadline exceeded")
                cell = source_cells.get((bucket, group))
                points.append({"time": bucket, "value": (
                    _transformed(cell_value(cell, request.metric, resolution), cell,
                                 request, resolution, bucket, zone, span_start, span_end)
                    if cell else None), "samples": cell["samples"] if cell else 0,
                    "unpriced_usage_count": cell["unknown"] if cell else 0,
                    "partial": bool(cell["unknown"]) if cell else False})
            if request.transform == "cumulative":
                running = 0
                for point in points:
                    if point["value"] is not None:
                        running += point["value"]
                        point["value"] = running
            series.append({"key": public_key, "label": label, "filter_value": filter_value,
                           "points": points,
                           **({"detail": other_detail} if group == OTHER_GROUP and other_detail else {})})
        ranking = []
        for group in primary_selected:
            if group not in totals:
                continue
            key, label, filter_value = _public_dimension(request.group_by, group, project_labels, account_labels, agent_labels)
            cell = totals[group]
            value = cell_value(cell, request.metric, resolution)
            if value is None:
                pass
            elif request.transform == "per_conversation":
                value = value / len(cell["conversations"]) if cell["conversations"] else None
            elif request.transform == "rate":
                value /= max(1, span_end - span_start)
            ranking.append({"key": key, "label": label, "filter_value": filter_value,
                            "value": value, "samples": cell["samples"],
                            **({"detail": other_detail} if group == OTHER_GROUP and other_detail else {})})
        if has_other:
            other_cell = empty_cell()
            for group, cell in totals.items():
                if group not in primary_selected:
                    merge_cell(other_cell, cell)
            if other_cell["samples"]:
                other_value = cell_value(other_cell, request.metric, resolution)
                if other_value is None:
                    pass
                elif request.transform == "per_conversation":
                    other_value = (other_value / len(other_cell["conversations"])
                                   if other_cell["conversations"] else None)
                elif request.transform == "rate":
                    other_value /= max(1, span_end - span_start)
                ranking.append({"key": "other", "label": "Other", "filter_value": None,
                                "value": other_value, "samples": other_cell["samples"]})
        total = None
        if ranking:
            if request.metric == "quota_utilization":
                total = sum(cell["sum"] for cell in totals.values()) / sum(cell["count"] for cell in totals.values())
            elif request.metric.startswith("average_"):
                total_sum = sum(cell["sum"] for cell in totals.values())
                observed_by_minute = {}
                for cell in totals.values():
                    for minute, seconds in cell["observed_by_minute"].items():
                        observed_by_minute[minute] = max(observed_by_minute.get(minute, 0), seconds)
                observed = sum(observed_by_minute.values())
                total = total_sum / observed if observed else None
            else:
                total = sum(cell["sum"] for cell in totals.values())
                if request.metric == "estimated_cost_nano_usd" and not any(
                    cell["count"] for cell in totals.values()
                ):
                    total = None
            if total is not None and request.transform == "rate":
                total /= max(1, span_end - span_start)
            if total is not None and request.transform == "per_conversation":
                total /= max(1, conversation_count)
        output.append({"range": {"from": iso_utc(span_start), "to": iso_utc(span_end)},
                       "coverage": all_coverage[-1],
                       "series": series, "ranking": ranking, "summary": {
                           "value": total, "samples": coverage["minute_rows"],
                           "contributing_conversations": conversation_count}})
    if time.monotonic() > deadline:
        raise QueryLimit("query deadline exceeded")
    return {
        "metric": request.metric, "operation": request.operation, "rolling": request.rolling,
        "unit": (f"{unit}/second" if request.transform == "rate" else
                 f"{unit}/conversation" if request.transform == "per_conversation" else unit),
        "base_unit": unit,
        "transform": request.transform,
        "requested_range": {"from": request.from_.isoformat(), "to": request.to.isoformat()},
        "effective_range": output[0]["range"], "resolution": resolution,
        "timezone": request.timezone, "scope": "pack" if pack else "local",
        "series": output[0]["series"] if request.operation in ("timeline", "comparison") else [],
        "summary": output[0]["summary"] if request.operation in ("summary", "comparison") else None,
        "ranking": output[0]["ranking"] if request.operation == "ranking" else None,
        "comparison": output[1] if len(output) > 1 else None,
        "coverage": all_coverage[0],
        "price_provenance": _price_provenance(store, all_coverage[0]["price_versions"])
                            if request.metric == "estimated_cost_nano_usd" else [],
        "price_basis": ("Versioned repository list-rate estimate applied to recorded usage; "
                        "not a bill or historical provider charge. Unknown prices remain null."
                        if request.metric == "estimated_cost_nano_usd" else None),
        "revision": store.revision(),
    }


def coverage(store) -> dict:
    db = store.connect(readonly=True)
    try:
        grain = ("SELECT u.t AS t, u.cost_nano AS cost FROM {table} u JOIN dim_model m ON m.id=u.model "
                 "WHERE u.t {cmp} " + FLOOR_SQL + " AND (m.name!='<synthetic>' OR "
                 "u.input+u.cache_write+u.cache_read+u.output!=0)")
        usage = db.execute(
            "SELECT MIN(t),MAX(t),COUNT(*),SUM(cost IS NULL) FROM ("
            + grain.format(table="usage_minute", cmp=">=") + " UNION ALL "
            + grain.format(table="usage_hour", cmp="<") + ")").fetchone()
        sources = db.execute("SELECT 'tracked' AS status,'ok' AS quality,COUNT(*) AS count FROM plugin_cursors "
                             "HAVING COUNT(*) > 0").fetchall()
        spans = db.execute("SELECT start_ts,end_ts FROM stats_disabled_spans ORDER BY start_ts DESC LIMIT 100").fetchall()
        backfills = db.execute("SELECT state,COUNT(*) AS count FROM stats_backfill GROUP BY state").fetchall()
        db_bytes = sum(path.stat().st_size for path in (
            store.db_path, store.db_path.with_name(store.db_path.name + "-wal"),
        ) if path.exists())
        return {"earliest": iso_utc(usage[0]) if usage[0] is not None else None,
                "latest": iso_utc(usage[1]) if usage[1] is not None else None,
                "freshness_seconds": max(0, int(time.time()) - usage[1]) if usage[1] is not None else None,
                "minute_rows": usage[2], "quality_rows": 0,
                "unknown_cost_rows": usage[3] or 0,
                "sources": [dict(row) for row in sources],
                "disabled_spans": [{"from": iso_utc(row["start_ts"]),
                                    "to": iso_utc(row["end_ts"]) if row["end_ts"] else None} for row in spans],
                "backfill": {row["state"]: row["count"] for row in backfills},
                "db_bytes": db_bytes,
                "revision": store.revision()}
    finally:
        db.close()


def contributions(store, request: QueryRequest, *, limit: int, cursor: int) -> dict:
    deadline = time.monotonic() + DEADLINE_SECONDS
    if request.metric == "quota_utilization":
        raise ValueError("quota has no conversation contributions")
    start, end = minute_window(request)
    table = METRICS[request.metric][1]
    rows = _fetch(store, table, request.filters, start, end, "conversation_id", deadline, request.metric)
    grouped: dict[str, dict] = {}
    for index, row in enumerate(rows):
        if index % 1024 == 0 and time.monotonic() > deadline:
            raise QueryLimit("query deadline exceeded")
        group = row["conversation_id"]
        entry = grouped.setdefault(group, {"value": 0, "samples": 0, "unknown_rows": 0})
        value = _value(row, request.metric)
        if value is None:
            entry["unknown_rows"] += 1
        else:
            entry["value"] += value
            entry["samples"] += 1
    ordered = sorted(grouped.items(), key=lambda pair: (-pair[1]["value"], pair[0]))
    if time.monotonic() > deadline:
        raise QueryLimit("query deadline exceeded")
    page = ordered[cursor:cursor + limit]
    return {"items": [{"conversation_id": group, "value": item["value"] if item["samples"] else None,
                       "samples": item["samples"], "unknown_rows": item["unknown_rows"]}
                      for group, item in page],
            "next_cursor": cursor + limit if cursor + limit < len(ordered) else None,
            "total": len(ordered), "unit": METRICS[request.metric][0],
            "coverage": {"minute_rows": len(rows), "partial": any(item["unknown_rows"] for item in grouped.values())}}


def dimensions(store, *, dimension: str, filters: StatsFilters,
               start: int | None, end: int | None, limit: int, cursor: int) -> dict:
    if dimension not in _FILTER_COLUMNS:
        raise ValueError("unknown dimension")
    table = "quota_minutes" if dimension in ("account_id", "window") else "minute_usage"
    source = _usage_source(filters, dimension) if table == "minute_usage" else table
    if start is not None and end is not None:
        where, args = _where(table, filters, start, end)
    else:
        where, args = "1=1", []
        if table == "minute_usage":
            where += f" AND {_REAL_USAGE}"
        allowed = _allowed_filters(table)
        for key, value in filters.model_dump(exclude_none=True).items():
            if key not in allowed:
                raise ValueError(f"{key} is unavailable for {table}")
            where += f" AND {_FILTER_COLUMNS[key]}=?"
            args.append(value)
    deadline = time.monotonic() + DEADLINE_SECONDS
    groups = project_groups.groups_for(store) if dimension == "project" else None
    account_labels = _account_labels() if dimension == "account_id" else None
    db = store.connect(readonly=True)
    try:
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        if groups is not None:
            return _project_dimension(db, groups, source, where, args, limit, cursor)
        rows = db.execute(
            f"SELECT {dimension} AS value,COUNT(*) AS count FROM {source} WHERE {where} "
            f"GROUP BY {dimension} ORDER BY count DESC,value LIMIT ? OFFSET ?",
            (*args, limit + 1, cursor),
        ).fetchall()
        total = db.execute(
            f"SELECT COUNT(DISTINCT {dimension}) FROM {source} WHERE {where}", args,
        ).fetchone()[0]
        items = []
        for row in rows[:limit]:
            key, label, filter_value = _public_dimension(dimension, row["value"], None, account_labels)
            items.append({"key": key, "label": label, "filter_value": filter_value, "minute_rows": row["count"]})
        return {"items": items,
                "next_cursor": cursor + limit if len(rows) > limit else None,
                "total": total}
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            raise QueryLimit("dimension deadline exceeded") from exc
        raise
    finally:
        db.close()


def _project_dimension(db, groups: ProjectGroups, source: str, where: str, args: list,
                       limit: int, cursor: int) -> dict:
    counts: dict[str, int] = defaultdict(int)
    members: dict[str, int] = {}
    for row in db.execute(f"SELECT project AS value,COUNT(*) AS count FROM {source} WHERE {where} "
                          "GROUP BY project", args):
        group = groups.group_of(row["value"]) if row["value"] else OTHER_GROUP
        counts[group] += row["count"]
        if group == OTHER_GROUP:
            members[row["value"] or ""] = row["count"]
    detail = groups.other_detail(sorted(members, key=lambda raw: (-members[raw], raw))) if members else None
    labels = _project_labels(groups, detail["count"] if detail else 0)
    ordered = sorted((g for g in counts if g != OTHER_GROUP), key=lambda g: (-counts[g], labels.get(g, g)))
    if OTHER_GROUP in counts:
        ordered.append(OTHER_GROUP)
    items = []
    for group in ordered[cursor:cursor + limit]:
        key, label, filter_value = _public_dimension("project", group, labels)
        item = {"key": key, "label": label, "filter_value": filter_value, "minute_rows": counts[group]}
        if group == OTHER_GROUP and detail:
            item["detail"] = detail
        items.append(item)
    return {"items": items, "next_cursor": cursor + limit if cursor + limit < len(ordered) else None,
            "total": len(ordered)}


def execute_batch(store, items: list[dict]) -> dict:
    cap = time.monotonic() + BATCH_CAP_SECONDS
    memo: dict[str, dict] = {}
    results = []
    store = BatchStore(store)
    store.scan_metrics = frozenset(item.get("metric") for item in items) & set(activity_query.PLAIN_METRICS)
    try:
        return _run_batch(store, items, cap, memo, results)
    finally:
        store.release()


def _ledger_key(request: QueryRequest) -> tuple[str, int]:
    start, end = minute_window(request)
    body = request.model_dump(mode="json", by_alias=True, exclude={"from_", "to", "comparison"})
    if request.rolling is None:
        body["window"] = [start, end]
        body["compare"] = list(minute_window(request.comparison)) if request.comparison else None
    return answers.digest(body), end


def _item_fingerprint(view: BatchStore, request: QueryRequest) -> str:
    parts = [answers.base_fingerprint(view)]
    if request.group_by == "project":
        groups = project_groups.groups_for(view)
        held = view.fingerprints.get(("groups", id(groups)))
        if held is None:
            held = view.fingerprints[("groups", id(groups))] = answers.digest(
                sorted(groups.group.items()), sorted(groups.labels.items()), sorted(groups.folders.items()))
        parts.append(held)
    elif request.group_by == "account_id":
        parts.append(answers.digest(sorted(_account_labels().items())))
    elif request.group_by == "conversation_id":
        parts.append(answers.digest(sorted(agent_names.names_for(view).items())))
    if request.scope == "pack" and METRICS[request.metric][1] in pack_scope.PACK_TABLES:
        parts.append(pack_scope.signature(view, view))
    return answers.digest(*parts)


def _answer_item(view: BatchStore, item: dict, cap: float, state: str) -> dict:
    request = QueryRequest.model_validate(item)
    key, window_end = _ledger_key(request)
    return answers.serve(
        view, key=key, window_end=window_end, fingerprint=_item_fingerprint(view, request), state=state,
        compute=lambda target, deadline: execute(target, request, deadline),
        deadline=min(time.monotonic() + DEADLINE_SECONDS, cap), budget=DEADLINE_SECONDS,
        families=families_for(request.metric))


def _run_batch(store, items: list[dict], cap: float, memo: dict, results: list) -> dict:
    state = answers.plugin_state(store)
    for item in items:
        key = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
        if key not in memo:
            try:
                memo[key] = _answer_item(store, item, cap, state)
            except ValidationError as exc:
                memo[key] = {"ok": False, "error": {
                    "code": "invalid_stats_request",
                    "message": "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())}}
            except (ValueError, KeyError) as exc:
                memo[key] = {"ok": False, "error": {
                    "code": "stats_query_limit" if isinstance(exc, QueryLimit) else "invalid_stats_request",
                    "message": str(exc)}}
            except sqlite3.Error as exc:
                logger.warning("stats_batch_item_failed", error_type=type(exc).__name__, error=str(exc))
                memo[key] = {"ok": False, "error": {
                    "code": "stats_unavailable", "message": "statistics are temporarily unavailable"}}
        results.append(memo[key])
    return {"results": results, "revision": store.revision()}

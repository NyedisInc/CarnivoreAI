from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from src.core.db import db_path_for
from src.core.safe_io.readonly_db import READONLY_TIMEOUT_QUICK_S, connect_readonly
from src.core.stats import pack_scope
from src.core.stats.answers import digest
from src.core.stats.batch_store import BatchStore
from src.core.stats.project_groups import OTHER_GROUP, ProjectGroups, other_label
from src.core.stats.query_buckets import QueryLimit, iso_utc
from src.core.stats.store_port import StatsStoreLike
from src.models.stats import QueryRequest, StatsFilters


def new_coverage_tally() -> Dict[str, Any]:
    return {"minute_rows": 0, "unknown_value_rows": 0, "quality_rows": 0,
            "observed_minutes": set(), "price_versions": set(),
            "known_agent_seconds": 0.0, "unknown_agent_seconds": 0.0,
            "priced_usage_count": 0, "unpriced_usage_count": 0,
            "priced_token_total": 0, "unpriced_token_total": 0,
            "mixed_price_token_total": 0}


def finished_coverage_dict(data: Dict[str, Any], start: int, end: int) -> Dict[str, Any]:
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


def price_provenance(store: StatsStoreLike, versions: List[str]) -> List[Dict[str, Any]]:
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


def dedupe_quota_rows(local_rows: Sequence[Any], peer_batches: Sequence[Tuple[int, Sequence[Any]]], *,
                      step: Optional[int] = None, end: Optional[int] = None) -> List[Any]:
    local_buckets: Dict[Tuple[str, str, str], Set[int]] = defaultdict(set)
    for row in local_rows:
        acct_key = (str(row["provider"] or ""), str(row["account_id"] or ""), str(row["window"] or ""))
        ts = int(row["minute_ts"])
        local_buckets[acct_key].add(ts // pack_scope.GRAIN_5M * pack_scope.GRAIN_5M)
        local_buckets[acct_key].add(ts // pack_scope.GRAIN_HOUR * pack_scope.GRAIN_HOUR)
    chosen_peer: Dict[Tuple[int, str, str, str], Tuple[Tuple[float, str, int], Any]] = {}
    for grain, rows in peer_batches:
        g_step = pack_scope.GRAIN_5M if grain <= pack_scope.GRAIN_5M else pack_scope.GRAIN_HOUR
        for row in rows:
            ts = int(row["minute_ts"])
            bucket = ts // g_step * g_step
            acct_key = (str(row["provider"] or ""), str(row["account_id"] or ""), str(row["window"] or ""))
            if bucket in local_buckets.get(acct_key, ()):
                continue
            dedupe_key = (ts, acct_key[0], acct_key[1], acct_key[2])
            fetched = float(row["fetched_at"] or 0)
            host = str(row["host"]) if "host" in row.keys() and row["host"] is not None else ""
            existing = chosen_peer.get(dedupe_key)
            if existing is None:
                chosen_peer[dedupe_key] = ((fetched, host, grain), row)
            else:
                prev_fetched, prev_host, _ = existing[0]
                if fetched > prev_fetched or (fetched == prev_fetched and host < prev_host):
                    chosen_peer[dedupe_key] = ((fetched, host, grain), row)
    merged: List[Any] = list(local_rows)
    for (_, _, grain), row in chosen_peer.values():
        if step is not None and end is not None and grain > step:
            merged.extend(pack_scope.spread_hours([row], step, end, source_grain=grain))
        else:
            merged.append(row)
    merged.sort(key=lambda r: int(r["minute_ts"]))
    return merged


def pack_coverage_stamp(store: StatsStoreLike) -> str:
    app = pack_scope._open_app(store)
    if app is None:
        return ""
    with closing(app):
        try:
            if not pack_scope.has_table(app, pack_scope.COVERAGE_TABLE):
                return ""
            rows = app.execute(
                f"SELECT peer_install_id, updated_at, minute_rows FROM {pack_scope.COVERAGE_TABLE} ORDER BY peer_install_id"
            ).fetchall()
            return digest([tuple(r) for r in rows]) if rows else ""
        except sqlite3.Error:
            return ""


def coverage_with_pack(store: StatsStoreLike, local_cov: Dict[str, Any],
                       local_earliest: Optional[int], local_latest: Optional[int]) -> Tuple[Dict[str, Any], Optional[int]]:
    app = pack_scope._open_app(store)
    if app is None:
        return local_cov, local_latest
    with closing(app):
        try:
            if not pack_scope.has_table(app, pack_scope.COVERAGE_TABLE):
                return local_cov, local_latest
            rows = app.execute(
                f"SELECT peer_install_id, earliest_ts, latest_ts, minute_rows, unknown_cost_rows, "
                f"tracked_sources, db_bytes, updated_at FROM {pack_scope.COVERAGE_TABLE} ORDER BY peer_install_id"
            ).fetchall()
        except sqlite3.Error as exc:
            pack_scope._warn_unreadable(exc)
            return local_cov, local_latest
    if not rows:
        return local_cov, local_latest
    earliest = local_earliest
    latest = local_latest
    minute_rows = int(local_cov["minute_rows"])
    unknown_cost_rows = int(local_cov["unknown_cost_rows"])
    db_bytes = int(local_cov["db_bytes"])
    peers: List[Dict[str, Any]] = []
    for row in rows:
        p_earliest = int(row["earliest_ts"]) if row["earliest_ts"] is not None else None
        p_latest = int(row["latest_ts"]) if row["latest_ts"] is not None else None
        if p_earliest is not None:
            earliest = p_earliest if earliest is None else min(earliest, p_earliest)
        if p_latest is not None:
            latest = p_latest if latest is None else max(latest, p_latest)
        minute_rows += int(row["minute_rows"] or 0)
        unknown_cost_rows += int(row["unknown_cost_rows"] or 0)
        db_bytes += int(row["db_bytes"] or 0)
        peers.append({
            "peer_install_id": str(row["peer_install_id"]),
            "earliest": iso_utc(p_earliest) if p_earliest is not None else None,
            "latest": iso_utc(p_latest) if p_latest is not None else None,
            "minute_rows": int(row["minute_rows"] or 0),
            "unknown_cost_rows": int(row["unknown_cost_rows"] or 0),
            "tracked_sources": int(row["tracked_sources"] or 0),
            "db_bytes": int(row["db_bytes"] or 0),
            "updated_at": float(row["updated_at"]) if row["updated_at"] is not None else None,
        })
    out = {
        **local_cov,
        "earliest": iso_utc(earliest) if earliest is not None else None,
        "latest": iso_utc(latest) if latest is not None else None,
        "freshness_seconds": max(0, int(time.time()) - latest) if latest is not None else None,
        "minute_rows": minute_rows,
        "unknown_cost_rows": unknown_cost_rows,
        "db_bytes": db_bytes,
        "peers": peers,
    }
    return out, latest


def fetch_contributions_rows(store: StatsStoreLike, request: QueryRequest, table: str, start: int, end: int,
                             deadline: float, fetch_fn: Callable[..., List[Any]]) -> List[Any]:
    filters = pack_scope.normalize_filters_for_self(store, request.filters)
    if request.scope != "pack" or table not in pack_scope.PACK_TABLES:
        return fetch_fn(store, table, filters, start, end, "conversation_id", deadline, request.metric)
    view = store if isinstance(store, BatchStore) else BatchStore(store)
    try:
        pack = pack_scope.for_request(store, view, request, table, resolution="hour", start=start, end=end)
        if not pack:
            return fetch_fn(store, table, filters, start, end, "conversation_id", deadline, request.metric)
        rows: List[Any] = []
        for arm in pack.arms:
            rows.extend(fetch_fn(store, table, filters, start, end, "conversation_id", deadline, request.metric, arm))
        return rows
    finally:
        if view is not store:
            view.release()


def read_coverage_snapshot(store: StatsStoreLike, open_read_ctx: Callable[[StatsStoreLike], Any],
                           floor_sql: str, rev: int) -> Tuple[Dict[str, Any], Optional[int]]:
    with open_read_ctx(store) as db:
        grain = ("SELECT u.t AS t, u.cost_nano AS cost FROM {table} u JOIN dim_model m ON m.id=u.model "
                 "WHERE u.t {cmp} " + floor_sql + " AND (m.name!='<synthetic>' OR "
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
    out = {"earliest": iso_utc(usage[0]) if usage[0] is not None else None,
           "latest": iso_utc(usage[1]) if usage[1] is not None else None,
           "freshness_seconds": max(0, int(time.time()) - usage[1]) if usage[1] is not None else None,
           "minute_rows": usage[2], "quality_rows": 0,
           "unknown_cost_rows": usage[3] or 0,
           "sources": [dict(row) for row in sources],
           "disabled_spans": [{"from": iso_utc(row["start_ts"]),
                               "to": iso_utc(row["end_ts"]) if row["end_ts"] else None} for row in spans],
           "backfill": {row["state"]: row["count"] for row in backfills},
           "db_bytes": db_bytes,
           "revision": rev}
    return coverage_with_pack(store, out, usage[0], usage[1])


def _peer_dimension_counts(app: sqlite3.Connection, dimension: str, table: str, filters: StatsFilters,
                           start: Optional[int], end: Optional[int], deadline: float,
                           dim_where_fn: Callable[[str, StatsFilters, Optional[int], Optional[int]], Tuple[str, List[Any]]]) -> Dict[Any, int]:
    counts: Dict[Any, int] = defaultdict(int)
    if filters.host == pack_scope.LOCAL:
        return counts
    if filters.hosts is not None and not any(h != pack_scope.LOCAL for h in filters.hosts):
        return counts
    app.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
    try:
        if table == "quota_minutes":
            if pack_scope.has_table(app, pack_scope.QUOTA_TABLE):
                where, args = dim_where_fn("quota_minutes", filters, start, end)
                source = (
                    f"(SELECT bucket_ts AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, "
                    f"COALESCE(account_id,'') AS account_id, COALESCE(window,'') AS window, utilization, fetched_at, "
                    f"COALESCE(state,'ok') AS state FROM {pack_scope.QUOTA_TABLE})"
                )
                for row in app.execute(
                        f"SELECT {dimension} AS value, COUNT(*) AS count FROM {source} WHERE {where} GROUP BY {dimension}", args):
                    if row["value"] not in (None, ""):
                        counts[row["value"]] += int(row["count"])
            if dimension == "account_id" and pack_scope.has_usage_meta_columns(app):
                usage_filters = StatsFilters.model_validate({
                    k: v for k, v in filters.model_dump(exclude_none=True).items() if k != "window"
                })
                u_where, u_args = dim_where_fn("minute_usage", usage_filters, start, end)
                source = pack_scope.peer_usage_sql(app)
                for row in app.execute(
                        f"SELECT account_id AS value, COUNT(*) AS count FROM {source} "
                        f"WHERE {u_where} AND account_id != ? GROUP BY account_id", (*u_args, "unknown")):
                    counts[row["value"]] += int(row["count"])
            return counts
        if not pack_scope.has_table(app, pack_scope.USAGE_TABLE):
            return counts
        where, args = dim_where_fn("minute_usage", filters, start, end)
        source = pack_scope.peer_usage_sql(app)
        for row in app.execute(
                f"SELECT {dimension} AS value, COUNT(*) AS count FROM {source} WHERE {where} GROUP BY {dimension}", args):
            counts[row["value"]] += int(row["count"])
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            raise QueryLimit("dimension deadline exceeded") from exc
        pack_scope._warn_unreadable(exc)
    finally:
        app.set_progress_handler(None, 0)
    return counts


def merge_dimension_counts(store: StatsStoreLike, *, dimension: str, table: str, filters: StatsFilters,
                           start: Optional[int], end: Optional[int], limit: int, cursor: int,
                           deadline: float, local_counts: Dict[Any, int], scope: str,
                           groups: Optional[ProjectGroups], account_labels: Optional[Dict[str, str]],
                           public_dimension: Callable[..., Tuple[str, str, Optional[str]]],
                           dim_where_fn: Callable[[str, StatsFilters, Optional[int], Optional[int]], Tuple[str, List[Any]]]) -> Dict[str, Any]:
    combined: Dict[Any, int] = defaultdict(int, local_counts)
    effective_groups = groups
    if scope == "pack":
        app = pack_scope._open_app(store)
        if app is not None:
            with closing(app):
                peer_counts = _peer_dimension_counts(
                    app, dimension, table, filters, start, end, deadline, dim_where_fn,
                )
            for value, count in peer_counts.items():
                combined[value] += count
        if effective_groups is not None:
            effective_groups = pack_scope.pack_groups(store, effective_groups)
    if effective_groups is not None:
        folded: Dict[str, int] = defaultdict(int)
        members: Dict[str, int] = {}
        for raw, count in combined.items():
            group = effective_groups.group_of(raw) if raw else OTHER_GROUP
            folded[group] += count
            if group == OTHER_GROUP:
                members[raw or ""] = members.get(raw or "", 0) + count
        detail = effective_groups.other_detail(sorted(members, key=lambda raw: (-members[raw], raw))) if members else None
        labels = {**effective_groups.labels, OTHER_GROUP: other_label(detail["count"] if detail else 0)}
        ordered = sorted((g for g in folded if g != OTHER_GROUP), key=lambda g: (-folded[g], labels.get(g, g)))
        if OTHER_GROUP in folded:
            ordered.append(OTHER_GROUP)
        items = []
        for group in ordered[cursor:cursor + limit]:
            key, label, filter_value = public_dimension("project", group, labels)
            item: Dict[str, Any] = {"key": key, "label": label, "filter_value": filter_value, "minute_rows": folded[group]}
            if group == OTHER_GROUP and detail:
                item["detail"] = detail
            items.append(item)
        return {
            "items": items,
            "next_cursor": cursor + limit if cursor + limit < len(ordered) else None,
            "total": len(ordered),
        }
    all_rows = sorted(combined.items(), key=lambda pair: (-pair[1], "" if pair[0] is None else str(pair[0])))
    total = len(all_rows)
    items = []
    for raw_val, count in all_rows[cursor:cursor + limit]:
        key, label, filter_value = public_dimension(dimension, raw_val, None, account_labels)
        items.append({"key": key, "label": label, "filter_value": filter_value, "minute_rows": count})
    return {
        "items": items,
        "next_cursor": cursor + limit if cursor + limit < total else None,
        "total": total,
    }


def _row_dict(conv: str, project: str, model: str, value: Any, tokens: int, first_ts: int, last_ts: int) -> Dict[str, Any]:
    return {
        "conversation_id": conv, "project": project, "model": model,
        "value": value, "tokens": tokens, "first_ts": first_ts, "last_ts": last_ts,
    }


def insights_grouped_with_pack(store: StatsStoreLike, filters: StatsFilters, start: int, end: int, metric: str,
                               metric_sql: str, deadline: float, max_rows: int, *, scope: str,
                               usage_source_fn: Callable[[StatsFilters, Optional[str]], str],
                               where_fn: Callable[..., Tuple[str, List[Any]]]) -> List[Any]:
    norm = pack_scope.normalize_filters_for_self(store, filters)
    where, args = where_fn("minute_usage", norm, start, end)
    local_source = usage_source_fn(norm, None)
    owned: Optional[pack_scope.Ownership] = None
    if scope == "pack":
        view = store if isinstance(store, BatchStore) else BatchStore(store)
        try:
            owned = pack_scope.ownership(store, view)
        finally:
            if view is not store:
                view.release()

    rows: List[Any] = []
    include_local = norm.host in (None, pack_scope.LOCAL) and (norm.hosts is None or pack_scope.LOCAL in norm.hosts)
    if include_local:
        l_where, l_args = where, list(args)
        if owned and owned.local_loses:
            l_where += f" AND NOT ({pack_scope._LOCAL_LOSES})"
            l_args.append(json.dumps(sorted(owned.local_loses)))
        db = store.connect(readonly=True)
        try:
            db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
            local_rows = db.execute(
                f"SELECT conversation_id,project,model,{metric_sql} AS value,"
                "SUM(input_tokens+cache_write_tokens+cache_read_tokens+output_tokens) AS tokens,"
                "MIN(minute_ts) AS first_ts,MAX(minute_ts) AS last_ts "
                f"FROM {local_source} WHERE {l_where} GROUP BY conversation_id,project,model "
                "ORDER BY conversation_id,project,model LIMIT ?",
                (*l_args, max_rows + 1),
            ).fetchall()
            if len(local_rows) > max_rows:
                raise QueryLimit("query exceeds row budget; narrow the range")
            rows.extend(local_rows)
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise QueryLimit("query deadline exceeded") from exc
            raise
        finally:
            db.close()

    if scope != "pack":
        return rows
    include_peers = norm.host != pack_scope.LOCAL and (norm.hosts is None or any(h != pack_scope.LOCAL for h in norm.hosts))
    if not include_peers:
        return rows
    app = pack_scope._open_app(store)
    if app is None:
        return rows
    seen_convs: Set[str] = {str(r["conversation_id"]) for r in rows}
    with closing(app):
        try:
            app.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
            if pack_scope.has_table(app, pack_scope.USAGE_TABLE):
                p_where, p_args = where, list(args)
                if owned and owned.peer_loses:
                    p_where += f" AND NOT ({pack_scope._PEER_LOSES})"
                    p_args.append(json.dumps(sorted(owned.peer_loses)))
                peer_source = pack_scope.peer_usage_sql(app)
                peer_rows = app.execute(
                    f"SELECT conversation_id,project,model,{metric_sql} AS value,"
                    "SUM(input_tokens+cache_write_tokens+cache_read_tokens+output_tokens) AS tokens,"
                    "MIN(minute_ts) AS first_ts,MAX(minute_ts) AS last_ts "
                    f"FROM {peer_source} WHERE {p_where} GROUP BY conversation_id,project,model "
                    "ORDER BY conversation_id,project,model LIMIT ?",
                    (*p_args, max_rows + 1),
                ).fetchall()
                if len(rows) + len(peer_rows) > max_rows:
                    raise QueryLimit("query exceeds row budget; narrow the range")
                for pr in peer_rows:
                    rows.append(pr)
                    seen_convs.add(str(pr["conversation_id"]))
            if pack_scope.has_table(app, pack_scope.CONVERSATIONS_TABLE):
                c_clauses = ["ended_at >= ?", "started_at < ?"]
                c_args: List[Any] = [start, end]
                if norm.host:
                    c_clauses.append("peer_install_id = ?")
                    c_args.append(norm.host)
                if norm.hosts:
                    c_clauses.append(f"peer_install_id IN ({','.join('?' * len(norm.hosts))})")
                    c_args.extend(norm.hosts)
                for field in ("provider", "project", "model", "agent_kind", "conversation_id", "account_id", "subagent_type"):
                    val = getattr(norm, field, None)
                    if val is not None:
                        c_clauses.append(f"{field} = ?")
                        c_args.append(val)
                conv_rows = app.execute(
                    f"SELECT peer_install_id, conversation_id, project, model, started_at, ended_at, tokens, cost_nano, turns "
                    f"FROM {pack_scope.CONVERSATIONS_TABLE} WHERE {' AND '.join(c_clauses)} ORDER BY peer_install_id, conversation_id",
                    c_args,
                ).fetchall()
                for cr in conv_rows:
                    cid = str(cr["conversation_id"])
                    if cid in seen_convs:
                        continue
                    seen_convs.add(cid)
                    if metric == "estimated_cost_nano_usd":
                        val = cr["cost_nano"]
                    elif metric == "usage_count":
                        val = int(cr["turns"] or 0)
                    else:
                        val = int(cr["tokens"] or 0)
                    rows.append(_row_dict(
                        cid, str(cr["project"] or ""), str(cr["model"] or ""), val,
                        int(cr["tokens"] or 0), int(cr["started_at"] or start), int(cr["ended_at"] or start),
                    ))
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc):
                raise QueryLimit("query deadline exceeded") from exc
            pack_scope._warn_unreadable(exc)
        finally:
            app.set_progress_handler(None, 0)
    return rows


def peer_conversation_meta(store: StatsStoreLike, ids: Sequence[str]) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
    if not ids:
        return {}
    app = pack_scope._open_app(store)
    if app is None:
        return {}
    with closing(app):
        try:
            if not pack_scope.has_table(app, pack_scope.CONVERSATIONS_TABLE):
                return {}
            marks = ",".join("?" * len(ids))
            out: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
            for row in app.execute(
                f"SELECT conversation_id, MIN(started_at), MAX(ended_at) FROM {pack_scope.CONVERSATIONS_TABLE} "
                f"WHERE conversation_id IN ({marks}) GROUP BY conversation_id",
                list(ids),
            ):
                out[str(row[0])] = (
                    int(row[1]) if row[1] is not None else None,
                    int(row[2]) if row[2] is not None else None,
                )
            return out
        except sqlite3.Error:
            return {}


def list_events_with_pack(store: StatsStoreLike, *, start: int, end: int, kind: Optional[str],
                          limit: int, cursor: int, scope: str,
                          subject_label: Callable[[str, str], str]) -> Dict[str, Any]:
    where, args = "occurred_at>=? AND occurred_at<?", [start, end]
    if kind:
        where += " AND kind=?"
        args.append(kind)
    fetch_cap = cursor + limit + 1
    with store.connect(readonly=True) as conn:
        local_rows = conn.execute(
            f"SELECT id,occurred_at,kind,subject,data FROM stats_events WHERE {where} "
            "ORDER BY occurred_at DESC,id DESC LIMIT ?",
            (*args, fetch_cap),
        ).fetchall()

    peer_rows: List[sqlite3.Row] = []
    if scope == "pack":
        app = pack_scope._open_app(store)
        if app is not None:
            with closing(app):
                try:
                    if pack_scope.has_table(app, pack_scope.EVENTS_TABLE):
                        peer_rows = app.execute(
                            f"SELECT peer_install_id, event_id, occurred_at, kind, subject, data "
                            f"FROM {pack_scope.EVENTS_TABLE} WHERE {where} "
                            "ORDER BY occurred_at DESC, peer_install_id DESC, event_id DESC LIMIT ?",
                            (*args, fetch_cap),
                        ).fetchall()
                except sqlite3.Error as exc:
                    pack_scope._warn_unreadable(exc)

    if not peer_rows:
        page = local_rows[cursor:cursor + limit]
        return {
            "items": [{
                "id": r["id"], "occurred_at": r["occurred_at"], "kind": r["kind"],
                "subject": r["subject"], "label": subject_label(r["kind"], r["subject"]),
                "data": json.loads(r["data"]),
            } for r in page],
            "next_cursor": cursor + limit if len(local_rows) > cursor + limit else None,
        }

    combined: List[Tuple[Tuple[int, int, Any], Dict[str, Any]]] = []
    for r in local_rows:
        ev_id = int(r["id"])
        combined.append((
            (-int(r["occurred_at"]), 0, -ev_id),
            {
                "id": ev_id, "occurred_at": int(r["occurred_at"]), "kind": str(r["kind"]),
                "subject": str(r["subject"]), "label": subject_label(str(r["kind"]), str(r["subject"])),
                "data": json.loads(r["data"] or "{}"),
            },
        ))
    for r in peer_rows:
        peer_id = str(r["peer_install_id"])
        ev_key = f"{peer_id}:{r['event_id']}"
        combined.append((
            (-int(r["occurred_at"]), 1, ev_key),
            {
                "id": ev_key, "occurred_at": int(r["occurred_at"]), "kind": str(r["kind"]),
                "subject": str(r["subject"]), "label": subject_label(str(r["kind"]), str(r["subject"])),
                "data": json.loads(r["data"] or "{}"), "host": peer_id,
            },
        ))
    combined.sort(key=lambda pair: pair[0][2] if pair[0][1] == 1 else "", reverse=True)
    combined.sort(key=lambda pair: (
        pair[0][0],
        pair[0][1],
        pair[0][2] if pair[0][1] == 0 else 0,
    ))
    page_items = [item for _, item in combined[cursor:cursor + limit]]
    return {
        "items": page_items,
        "next_cursor": cursor + limit if len(combined) > cursor + limit else None,
    }


def session_usage_peer_activity(conn: sqlite3.Connection, lo: int, hi: int,
                                local_conv_hours: Set[Tuple[str, int]]) -> Dict[str, Any]:
    if not pack_scope.has_table(conn, pack_scope.ACTIVITY_TABLE):
        return {"rows": [], "since": None}
    since_row = conn.execute(f"SELECT MIN(bucket_ts) FROM {pack_scope.ACTIVITY_TABLE}").fetchone()
    since = int(since_row[0]) if since_row and since_row[0] is not None else None
    raw = conn.execute(
        f"SELECT peer_install_id, conversation_id, bucket_ts, grain, working_seconds, "
        f"strftime('%Y-%m-%d', bucket_ts, 'unixepoch', 'localtime') AS day "
        f"FROM {pack_scope.ACTIVITY_TABLE} WHERE bucket_ts >= ? AND bucket_ts < ?",
        (lo, hi),
    ).fetchall()
    if not raw:
        return {"rows": [], "since": since}
    has_5m: Set[Tuple[str, str, int]] = {
        (str(r[0]), str(r[1]), int(r[2]) // 3600 * 3600) for r in raw if int(r[3]) == pack_scope.GRAIN_5M
    }
    best_peer: Dict[Tuple[str, int], str] = {}
    for r in raw:
        peer, conv, hour = str(r[0]), str(r[1]), int(r[2]) // 3600 * 3600
        if (conv, hour) in local_conv_hours:
            continue
        prev = best_peer.get((conv, hour))
        if prev is None or peer < prev:
            best_peer[(conv, hour)] = peer
    agg_work: Dict[Tuple[str, str], float] = defaultdict(float)
    agg_last: Dict[Tuple[str, str], Optional[int]] = {}
    for r in raw:
        peer, conv, ts, grain, working, day = str(r[0]), str(r[1]), int(r[2]), int(r[3]), float(r[4] or 0.0), str(r[5])
        hour = ts // 3600 * 3600
        if best_peer.get((conv, hour)) != peer:
            continue
        if grain == pack_scope.GRAIN_HOUR and (peer, conv, hour) in has_5m:
            continue
        key = (conv, day)
        agg_work[key] += working
        if working > 0:
            prev_ts = agg_last.get(key)
            agg_last[key] = ts if prev_ts is None else max(prev_ts, ts)
        else:
            agg_last.setdefault(key, None)
    rows = [(conv, day, work, agg_last.get((conv, day))) for (conv, day), work in agg_work.items()]
    return {"rows": rows, "since": since}


def mcp_usage_merge_pack(per: Dict[str, Dict[str, Any]], last: Dict[str, str], first: date, today: date, *,
                         app_db: Optional[Path] = None) -> None:
    if app_db is None:
        try:
            from src.config import settings
            app_db = db_path_for(settings.get_state_dir())
        except RuntimeError:
            return
    if not app_db.exists():
        return
    try:
        conn = connect_readonly(app_db, timeout=READONLY_TIMEOUT_QUICK_S)
    except sqlite3.Error:
        return
    with closing(conn):
        try:
            if not pack_scope.has_table(conn, pack_scope.MCP_TABLE):
                return
            first_ts = int(datetime(first.year, first.month, first.day, tzinfo=timezone.utc).timestamp())
            end_day = today + timedelta(days=1)
            end_ts = int(datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone.utc).timestamp())
            rows = conn.execute(
                f"SELECT tool, SUM(calls), SUM(errors) FROM {pack_scope.MCP_TABLE} "
                "WHERE hour >= ? AND hour < ? GROUP BY tool",
                (first_ts, end_ts),
            ).fetchall()
            for tool, calls_raw, errors_raw in rows:
                tool_name = str(tool)
                calls = int(calls_raw or 0)
                errors = int(errors_raw or 0)
                if calls <= 0:
                    continue
                entry = per.setdefault(tool_name, {"total": 0, "by_caller_kind": {}, "by_outcome": {}})
                entry["total"] += calls
                entry["by_caller_kind"]["pack"] = entry["by_caller_kind"].get("pack", 0) + calls
                ok_calls = max(0, calls - errors)
                if ok_calls:
                    entry["by_outcome"]["ok"] = entry["by_outcome"].get("ok", 0) + ok_calls
                if errors:
                    entry["by_outcome"]["error"] = entry["by_outcome"].get("error", 0) + errors
            for tool, max_hour in conn.execute(
                    f"SELECT tool, MAX(hour) FROM {pack_scope.MCP_TABLE} GROUP BY tool"):
                if max_hour is None:
                    continue
                day_str = datetime.fromtimestamp(int(max_hour), tz=timezone.utc).date().isoformat()
                prev = last.get(str(tool))
                if prev is None or day_str > prev:
                    last[str(tool)] = day_str
        except sqlite3.Error as exc:
            pack_scope._warn_unreadable(exc)

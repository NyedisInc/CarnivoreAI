from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

import structlog

from src.core.db import db_path_for
from src.core.db_models import META_INSTALL_ID
from src.core.db_reuse.deadline_loan import DeadlineLoan
from src.core.db_reuse.pooled_read import POOL_LIMIT, fresh_for_read
from src.core.db_reuse.thread_connections import ThreadConnections
from src.core.pack.rollup_import import ddl as _rollup_ddl
from src.core.pack.rollup_import.ddl import (
    COUNTER_TABLE,
    META_TABLE,
    PROJECTS_TABLE,
    RELAY_REV_KEY,
    STATE_TABLE,
    USAGE_TABLE,
)
from src.core.safe_io.readonly_db import READONLY_TIMEOUT_DEFAULT_S, connect_readonly
from src.core.stats import project_groups
from src.core.stats.answers import digest
from src.core.stats.plugin.extract import project_key
from src.core.stats.project_groups import ProjectGroups

logger = structlog.get_logger()

USAGE_5M_TABLE: str = getattr(_rollup_ddl, "USAGE_5M_TABLE", "pack_rollups_5m")
ACTIVITY_TABLE: str = getattr(_rollup_ddl, "ACTIVITY_TABLE", "pack_rollup_activity")
QUOTA_TABLE: str = getattr(_rollup_ddl, "QUOTA_TABLE", "pack_rollup_quota")
CONVERSATIONS_TABLE: str = getattr(_rollup_ddl, "CONVERSATIONS_TABLE", "pack_rollup_conversations")
EVENTS_TABLE: str = getattr(_rollup_ddl, "EVENTS_TABLE", "pack_rollup_events")
COVERAGE_TABLE: str = getattr(_rollup_ddl, "COVERAGE_TABLE", "pack_rollup_coverage")
MCP_TABLE: str = getattr(_rollup_ddl, "MCP_TABLE", "pack_rollup_mcp")

LOCAL = "local"
PACK_TABLES = ("minute_usage", "minute_counters", "activity_minutes", "quota_minutes")
_UNKNOWN = "unknown"
WARN_EVERY_SECONDS = 600.0
GRAIN_5M = 300
GRAIN_HOUR = 3600

_PEER_USAGE_V112 = (
    f"(SELECT hour AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, conversation_id, project, model, "
    "COALESCE(agent_kind,'') AS agent_kind, input AS input_tokens, cache_write AS cache_write_tokens, "
    "cache_read AS cache_read_tokens, output AS output_tokens, "
    "CASE WHEN priced > 0 THEN cost_nano END AS estimated_cost_nano_usd, NULL AS price_version, messages AS usage_count, "
    "priced AS priced_usage_count, messages - priced AS unpriced_usage_count, 'ok' AS quality, "
    f"'{_UNKNOWN}' AS account_id, '{_UNKNOWN}' AS subagent_type FROM {USAGE_TABLE})"
)
_PEER_USAGE_V113 = (
    f"(SELECT hour AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, conversation_id, project, model, "
    "COALESCE(agent_kind,'') AS agent_kind, input AS input_tokens, cache_write AS cache_write_tokens, "
    "cache_read AS cache_read_tokens, output AS output_tokens, "
    "CASE WHEN priced > 0 THEN cost_nano END AS estimated_cost_nano_usd, NULL AS price_version, messages AS usage_count, "
    "priced AS priced_usage_count, messages - priced AS unpriced_usage_count, 'ok' AS quality, "
    f"COALESCE(NULLIF(account_id,''),'{_UNKNOWN}') AS account_id, "
    f"COALESCE(NULLIF(subagent_type,''),'{_UNKNOWN}') AS subagent_type FROM {USAGE_TABLE})"
)
_PEER_USAGE = _PEER_USAGE_V113
_PEER_USAGE_5M = (
    f"(SELECT bucket_5m AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, conversation_id, project, model, "
    "COALESCE(agent_kind,'') AS agent_kind, input AS input_tokens, cache_write AS cache_write_tokens, "
    "cache_read AS cache_read_tokens, output AS output_tokens, "
    "CASE WHEN priced > 0 THEN cost_nano END AS estimated_cost_nano_usd, NULL AS price_version, messages AS usage_count, "
    "priced AS priced_usage_count, messages - priced AS unpriced_usage_count, 'ok' AS quality, "
    f"COALESCE(NULLIF(account_id,''),'{_UNKNOWN}') AS account_id, "
    f"COALESCE(NULLIF(subagent_type,''),'{_UNKNOWN}') AS subagent_type FROM {USAGE_5M_TABLE})"
)
_PEER_COUNTERS = (
    "(SELECT hour AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, conversation_id, project, model, "
    f"COALESCE(agent_kind,'') AS agent_kind, counter, key, value FROM {COUNTER_TABLE})"
)
_PEER_ACTIVITY_HOUR = (
    "(SELECT bucket_ts AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, conversation_id, project, model, "
    "COALESCE(agent_kind,'') AS agent_kind, observed_seconds, working_seconds, running_seconds, starts, completions, "
    f"waiting_seconds, subagent_seconds, global_observed_seconds FROM {ACTIVITY_TABLE} WHERE grain = {GRAIN_HOUR})"
)
_PEER_ACTIVITY_5M = (
    "(SELECT bucket_ts AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, conversation_id, project, model, "
    "COALESCE(agent_kind,'') AS agent_kind, observed_seconds, working_seconds, running_seconds, starts, completions, "
    f"waiting_seconds, subagent_seconds, global_observed_seconds FROM {ACTIVITY_TABLE} WHERE grain = {GRAIN_5M})"
)
_PEER_QUOTA_HOUR = (
    "(SELECT bucket_ts AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, "
    "COALESCE(account_id,'') AS account_id, COALESCE(window,'') AS window, utilization, fetched_at, "
    f"COALESCE(state,'ok') AS state FROM {QUOTA_TABLE} WHERE grain = {GRAIN_HOUR})"
)
_PEER_QUOTA_5M = (
    "(SELECT bucket_ts AS minute_ts, peer_install_id AS host, COALESCE(provider,'') AS provider, "
    "COALESCE(account_id,'') AS account_id, COALESCE(window,'') AS window, utilization, fetched_at, "
    f"COALESCE(state,'ok') AS state FROM {QUOTA_TABLE} WHERE grain = {GRAIN_5M})"
)
_LOCAL_LOSES = "(conversation_id || '|' || (minute_ts / 3600 * 3600)) IN (SELECT value FROM json_each(?))"
_PEER_LOSES = "(host || '|' || conversation_id || '|' || (minute_ts / 3600 * 3600)) IN (SELECT value FROM json_each(?))"
_PEER_HOUR_COVERED = "(host || '|' || (minute_ts / 3600 * 3600)) IN (SELECT value FROM json_each(?))"


def has_table(app: sqlite3.Connection, table: str) -> bool:
    row = app.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def has_usage_meta_columns(app: sqlite3.Connection) -> bool:
    cols = {row[1] for row in app.execute(f"PRAGMA table_info({USAGE_TABLE})")}
    return "account_id" in cols and "subagent_type" in cols


def peer_usage_sql(app: sqlite3.Connection) -> str:
    return _PEER_USAGE_V113 if has_usage_meta_columns(app) else _PEER_USAGE_V112


def _table_has_rows(app: sqlite3.Connection, table: str) -> bool:
    if not has_table(app, table):
        return False
    return app.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None


def _open_app_read(path: Path) -> sqlite3.Connection:
    conn = connect_readonly(path, timeout=READONLY_TIMEOUT_DEFAULT_S)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA cache_size=-16000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=67108864")
    return conn


_APP_READS = ThreadConnections(_open_app_read, limit=POOL_LIMIT)


@dataclass(frozen=True)
class Arm:

    source: Optional[str] = None
    skip: Optional[str] = None
    args: Tuple[Any, ...] = ()
    carnivore: Optional[Path] = None
    grain: int = GRAIN_HOUR

    def where(self) -> Tuple[str, List[Any]]:
        return (f" AND NOT ({self.skip})", list(self.args)) if self.skip else ("", [])

    def connect(self, store: Any) -> Any:
        if self.carnivore is None:
            return store.connect(readonly=True)
        return DeadlineLoan(fresh_for_read(_APP_READS.get(self.carnivore)), lambda: _APP_READS.discard(self.carnivore))


@dataclass(frozen=True)
class Ownership:

    signature: str
    local_loses: FrozenSet[str] = frozenset()
    peer_loses: FrozenSet[str] = frozenset()
    has_peers: bool = False


@dataclass(frozen=True)
class PackQuery:

    arms: Tuple[Arm, ...]


_warn_lock = threading.Lock()
_warned_at = 0.0
_cache_lock = threading.Lock()
_inflight_locks: Dict[str, threading.Lock] = {}
_cache: Dict[str, Tuple[Tuple[int, str], Ownership]] = {}


def _warn_unreadable(error: Exception) -> None:
    global _warned_at
    with _warn_lock:
        if time.monotonic() - _warned_at < WARN_EVERY_SECONDS and _warned_at:
            return
        _warned_at = time.monotonic()
    logger.warning("stats_pack_scope_unreadable", error_type=type(error).__name__, detail=str(error)[:120])


def _app_path(store: Any) -> Path:
    return db_path_for(store.state_dir)


def _open_app(store: Any) -> Optional[sqlite3.Connection]:
    path = _app_path(store)
    if not path.exists():
        return None
    try:
        return Arm(carnivore=path).connect(store)
    except sqlite3.Error as exc:
        _warn_unreadable(exc)
        return None


def self_install_id(store: Any) -> Optional[str]:
    app = _open_app(store)
    if app is None:
        return None
    with closing(app):
        try:
            row = app.execute("SELECT value FROM meta WHERE key = ?", (META_INSTALL_ID,)).fetchone()
            return str(row[0]) if row and row[0] else None
        except sqlite3.Error:
            return None


def normalize_filters_for_self(store: Any, filters: Any) -> Any:
    host = getattr(filters, "host", None)
    hosts = getattr(filters, "hosts", None)
    if host is None and hosts is None:
        return filters
    if host == LOCAL and hosts is None:
        return filters
    self_id = self_install_id(store)
    if not self_id:
        return filters
    updates: Dict[str, Any] = {}
    if host == self_id:
        updates["host"] = LOCAL
    if hosts is not None and self_id in hosts:
        seen: Set[str] = set()
        rewritten: List[str] = []
        for entry in hosts:
            mapped = LOCAL if entry == self_id else entry
            if mapped not in seen:
                seen.add(mapped)
                rewritten.append(mapped)
        updates["hosts"] = rewritten
    if not updates:
        return filters
    return filters.model_copy(update=updates)


def _v113_table_stamp(app: sqlite3.Connection) -> Tuple[Tuple[str, int, Any], ...]:
    parts: List[Tuple[str, int, Any]] = []
    for table, ts_col in ((USAGE_5M_TABLE, "bucket_5m"), (ACTIVITY_TABLE, "bucket_ts"), (QUOTA_TABLE, "bucket_ts")):
        if not has_table(app, table):
            continue
        row = app.execute(f"SELECT COUNT(*), MAX({ts_col}) FROM {table}").fetchone()
        count = int(row[0]) if row and row[0] else 0
        if count > 0:
            parts.append((table, count, row[1]))
    return tuple(parts)


def _rollup_state(app: sqlite3.Connection) -> List[Tuple[str, int, str, str, Any, Any]]:
    marker = app.execute(f"SELECT v FROM {META_TABLE} WHERE k = ?", (RELAY_REV_KEY,)).fetchone()
    names = digest([tuple(r) for r in app.execute(f"SELECT peer_install_id, project, name FROM {PROJECTS_TABLE} ORDER BY 1, 2")])
    return [(r[0], int(r[1]), str(r[2]), str(r[3]), marker[0] if marker else None, names) for r in app.execute(
        f"SELECT peer_install_id, revision, scope_digest, via FROM {STATE_TABLE} ORDER BY peer_install_id")]


def rollup_fingerprint(store: Any) -> Optional[str]:
    app = _open_app(store)
    if app is None:
        return None
    with closing(app):
        try:
            states = _rollup_state(app)
            v113 = _v113_table_stamp(app)
        except sqlite3.Error as exc:
            _warn_unreadable(exc)
            return None
    if not states and not v113:
        return None
    return digest(states, v113) if v113 else digest(states)


def project_homes(app: sqlite3.Connection) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for root, state, home, moved in app.execute(
            "SELECT root, pack_state, home_install_id, moved_to_install_id FROM projects WHERE pack_state != 'home'"):
        peer = moved if state == "moved_away" else home
        if root and peer:
            out[project_key(root)] = str(peer)
    return out


def _owners(store: Any, view: Any, app: sqlite3.Connection, signature: str) -> Ownership:
    db = view.connect(readonly=True)
    mine = {r[0] for r in db.execute("SELECT DISTINCT conversation_id FROM dim_source")}
    has_act = has_table(app, ACTIVITY_TABLE)
    if has_act:
        mine |= {r[0] for r in db.execute("SELECT DISTINCT conversation_id FROM dim_live WHERE conversation_id <> ''")}
    held: Dict[str, Set[str]] = {}
    for table in (USAGE_TABLE, COUNTER_TABLE):
        for conv, peer in app.execute(f"SELECT DISTINCT conversation_id, peer_install_id FROM {table}"):
            held.setdefault(conv, set()).add(peer)
    if has_table(app, USAGE_5M_TABLE):
        for conv, peer in app.execute(f"SELECT DISTINCT conversation_id, peer_install_id FROM {USAGE_5M_TABLE}"):
            held.setdefault(conv, set()).add(peer)
    if has_act:
        for conv, peer in app.execute(f"SELECT DISTINCT conversation_id, peer_install_id FROM {ACTIVITY_TABLE}"):
            held.setdefault(conv, set()).add(peer)
    overlap = sorted(c for c, holders in held.items() if c in mine or len(holders) > 1)
    if not overlap:
        return Ownership(signature, has_peers=True)
    ids = json.dumps(overlap)
    local: Dict[Tuple[str, int], str] = {}
    for table in ("usage_hour", "counter_hour"):
        for conv, hour, project in db.execute(
                f"SELECT s.conversation_id, u.t, p.name FROM dim_source s "
                f"JOIN {table} u ON u.src = s.id "
                f"JOIN dim_project p ON p.id = u.project "
                "WHERE s.conversation_id IN (SELECT value FROM json_each(?)) "
                "GROUP BY 1, 2, 3 ORDER BY 3 DESC", (ids,)):
            local[(conv, hour)] = project
    if has_act:
        for conv, hour, project in db.execute(
                "SELECT l.conversation_id, (a.t / 3600) * 3600, l.project FROM dim_live l "
                "JOIN activity_hour a ON a.live = l.id "
                "WHERE l.conversation_id IN (SELECT value FROM json_each(?)) "
                "GROUP BY 1, 2, 3 ORDER BY 3 DESC", (ids,)):
            local.setdefault((conv, hour), project)
    peers: Dict[Tuple[str, int], Set[str]] = {}
    hinted: Dict[Tuple[str, int], Set[str]] = {}
    hints = {(o, p): h for o, p, h in app.execute(f"SELECT peer_install_id, project, home_install_id FROM {PROJECTS_TABLE} WHERE home_install_id IS NOT NULL")}
    for table in (USAGE_TABLE, COUNTER_TABLE):
        for peer, conv, hour, project in app.execute(
                f"SELECT DISTINCT peer_install_id, conversation_id, hour, project FROM {table} "
                "WHERE conversation_id IN (SELECT value FROM json_each(?))", (ids,)):
            peers.setdefault((conv, hour), set()).add(peer)
            if (peer, project) in hints:
                hinted.setdefault((conv, hour), set()).add(hints[(peer, project)])
    if has_table(app, USAGE_5M_TABLE):
        for peer, conv, hour, project in app.execute(
                f"SELECT DISTINCT peer_install_id, conversation_id, (bucket_5m / 3600) * 3600, project FROM {USAGE_5M_TABLE} "
                "WHERE conversation_id IN (SELECT value FROM json_each(?))", (ids,)):
            peers.setdefault((conv, hour), set()).add(peer)
            if (peer, project) in hints:
                hinted.setdefault((conv, hour), set()).add(hints[(peer, project)])
    if has_act:
        for peer, conv, hour, project in app.execute(
                f"SELECT DISTINCT peer_install_id, conversation_id, (bucket_ts / 3600) * 3600, project FROM {ACTIVITY_TABLE} "
                "WHERE conversation_id IN (SELECT value FROM json_each(?))", (ids,)):
            peers.setdefault((conv, hour), set()).add(peer)
            if (peer, project) in hints:
                hinted.setdefault((conv, hour), set()).add(hints[(peer, project)])
    homes = project_homes(app)
    groups = project_groups.groups_for(store) if homes else None
    self_row = app.execute("SELECT value FROM meta WHERE key = ?", (META_INSTALL_ID,)).fetchone()
    self_id = str(self_row[0]) if self_row and self_row[0] else None
    local_loses: Set[str] = set()
    peer_loses: Set[str] = set()
    for key, holders in peers.items():
        here = key in local
        if not here and len(holders) == 1:
            continue
        home = homes.get(groups.group_of(local[key])) if (here and groups is not None) else None
        hint = sorted(h for h in hinted.get(key, ()) if h in holders or (h == self_id and here))
        if home in holders:
            owner = home
        elif hint:
            owner = LOCAL if hint[0] == self_id else hint[0]
        elif here:
            if self_id is not None:
                winner = min(holders | {self_id})
                owner = LOCAL if winner == self_id else winner
            else:
                owner = LOCAL
        else:
            owner = min(holders)
        if here and owner != LOCAL:
            local_loses.add(f"{key[0]}|{key[1]}")
        peer_loses.update(f"{peer}|{key[0]}|{key[1]}" for peer in holders if peer != owner)
    return Ownership(signature, frozenset(local_loses), frozenset(peer_loses), has_peers=True)


def ownership(store: Any, view: Any) -> Optional[Ownership]:
    held = view.fingerprints.get("pack")
    if held is not None:
        return held or None
    app = _open_app(store)
    result: Optional[Ownership] = None
    if app is not None:
        with closing(app):
            try:
                states = _rollup_state(app)
                v113 = _v113_table_stamp(app)
                if states or v113:
                    homes = project_homes(app)
                    grouping = sorted(project_groups.groups_for(store).group.items()) if homes else []
                    signature = digest(states, v113, sorted(homes.items()), grouping) if v113 else digest(
                        states, sorted(homes.items()), grouping)
                    key = (view.usage_revision(), signature)
                    sd_key = str(store.state_dir)
                    with _cache_lock:
                        hit = _cache.get(sd_key)
                        if hit is not None and hit[0] == key:
                            result = hit[1]
                            sd_lock = None
                        else:
                            sd_lock = _inflight_locks.setdefault(sd_key, threading.Lock())
                    if sd_lock is not None:
                        with sd_lock:
                            with _cache_lock:
                                hit = _cache.get(sd_key)
                            if hit is not None and hit[0] == key:
                                result = hit[1]
                            else:
                                result = _owners(store, view, app, signature)
                                with _cache_lock:
                                    _cache[sd_key] = (key, result)
            except sqlite3.Error as exc:
                _warn_unreadable(exc)
    view.fingerprints["pack"] = result or False
    return result


def signature(store: Any, view: Any) -> str:
    found = ownership(store, view)
    return found.signature if found is not None else "no-pack"


def _combine_skips(parts: List[Tuple[str, Any]]) -> Tuple[Optional[str], Tuple[Any, ...]]:
    if not parts:
        return None, ()
    if len(parts) == 1:
        return parts[0][0], (parts[0][1],)
    return " OR ".join(f"({expr})" for expr, _ in parts), tuple(arg for _, arg in parts)


def _covered_hours(app: sqlite3.Connection, table: str, ts_col: str, *, grain: Optional[int],
                   start: Optional[int], end: Optional[int]) -> List[str]:
    if not has_table(app, table):
        return []
    clauses: List[str] = []
    args: List[Any] = []
    if grain is not None:
        clauses.append("grain = ?")
        args.append(grain)
    if start is not None and end is not None:
        start_floor = start // GRAIN_HOUR * GRAIN_HOUR
        end_ceil = ((end + GRAIN_HOUR - 1) // GRAIN_HOUR) * GRAIN_HOUR
        clauses.append(f"{ts_col} >= ? AND {ts_col} < ?")
        args.extend([start_floor, end_ceil])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = app.execute(
        f"SELECT DISTINCT peer_install_id, ({ts_col} / 3600) * 3600 FROM {table}{where}", args,
    ).fetchall()
    return sorted(f"{row[0]}|{int(row[1])}" for row in rows)


def _peer_arms_for_table(app: sqlite3.Connection, app_path: Path, table: str, owned: Ownership, *,
                         resolution: Optional[str], start: Optional[int], end: Optional[int]) -> List[Arm]:
    fine = resolution in SPREAD_STEPS
    loses_json = json.dumps(sorted(owned.peer_loses)) if owned.peer_loses else None
    if table == "minute_counters":
        return [Arm(_PEER_COUNTERS, _PEER_LOSES, (loses_json,), app_path, GRAIN_HOUR)
                if loses_json else Arm(_PEER_COUNTERS, carnivore=app_path, grain=GRAIN_HOUR)]
    if table == "minute_usage":
        hour_sql = peer_usage_sql(app)
        covered_5m = _covered_hours(app, USAGE_5M_TABLE, "bucket_5m", grain=None, start=start, end=end) if fine else []
        arms: List[Arm] = []
        if covered_5m:
            arms.append(Arm(_PEER_USAGE_5M, _PEER_LOSES, (loses_json,), app_path, GRAIN_5M)
                        if loses_json else Arm(_PEER_USAGE_5M, carnivore=app_path, grain=GRAIN_5M))
            skips: List[Tuple[str, Any]] = []
            if loses_json:
                skips.append((_PEER_LOSES, loses_json))
            skips.append((_PEER_HOUR_COVERED, json.dumps(covered_5m)))
            skip_sql, skip_args = _combine_skips(skips)
            arms.append(Arm(hour_sql, skip_sql, skip_args, app_path, GRAIN_HOUR))
            return arms
        return [Arm(hour_sql, _PEER_LOSES, (loses_json,), app_path, GRAIN_HOUR)
                if loses_json else Arm(hour_sql, carnivore=app_path, grain=GRAIN_HOUR)]
    if table in ("activity_minutes", "quota_minutes"):
        is_act = table == "activity_minutes"
        tbl = ACTIVITY_TABLE if is_act else QUOTA_TABLE
        sql_5m = _PEER_ACTIVITY_5M if is_act else _PEER_QUOTA_5M
        sql_hr = _PEER_ACTIVITY_HOUR if is_act else _PEER_QUOTA_HOUR
        use_loses = loses_json if is_act else None
        primary_grain = GRAIN_5M if fine else GRAIN_HOUR
        fallback_grain = GRAIN_HOUR if fine else GRAIN_5M
        primary_sql = sql_5m if fine else sql_hr
        fallback_sql = sql_hr if fine else sql_5m
        primary_hours = _covered_hours(app, tbl, "bucket_ts", grain=primary_grain, start=start, end=end)
        fallback_hours = _covered_hours(app, tbl, "bucket_ts", grain=fallback_grain, start=start, end=end)
        arms = []
        if primary_hours:
            arms.append(Arm(primary_sql, _PEER_LOSES, (use_loses,), app_path, primary_grain)
                        if use_loses else Arm(primary_sql, carnivore=app_path, grain=primary_grain))
        if fallback_hours:
            skips = []
            if use_loses:
                skips.append((_PEER_LOSES, use_loses))
            if primary_hours:
                skips.append((_PEER_HOUR_COVERED, json.dumps(primary_hours)))
            skip_sql, skip_args = _combine_skips(skips)
            arms.append(Arm(fallback_sql, skip_sql, skip_args, app_path, fallback_grain))
        return arms
    return []


def for_request(store: Any, view: Any, request: Any, table: str, *,
                resolution: Optional[str] = None, start: Optional[int] = None,
                end: Optional[int] = None) -> Optional[PackQuery]:
    if getattr(request, "scope", "local") != "pack" or table not in PACK_TABLES:
        return None
    owned = ownership(store, view)
    if owned is None:
        return None
    app = _open_app(store)
    if app is None:
        return None
    with closing(app):
        try:
            if table == "activity_minutes" and not _table_has_rows(app, ACTIVITY_TABLE):
                return None
            if table == "quota_minutes" and not _table_has_rows(app, QUOTA_TABLE):
                return None
            filters = normalize_filters_for_self(store, request.filters)
            host = filters.host
            picked = filters.hosts
            arms: List[Arm] = []
            if table == "quota_minutes":
                arms.append(Arm())
                arms.extend(_peer_arms_for_table(
                    app, _app_path(store), table, owned, resolution=resolution, start=start, end=end))
                return PackQuery(tuple(arms))
            if host in (None, LOCAL) and (picked is None or LOCAL in picked):
                arms.append(Arm(skip=_LOCAL_LOSES, args=(json.dumps(sorted(owned.local_loses)),))
                            if owned.local_loses else Arm())
            if host != LOCAL and (picked is None or any(h != LOCAL for h in picked)):
                arms.extend(_peer_arms_for_table(
                    app, _app_path(store), table, owned, resolution=resolution, start=start, end=end))
            return PackQuery(tuple(arms))
        except sqlite3.Error as exc:
            _warn_unreadable(exc)
            return None


_SPREAD_FIELDS = (
    "input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens", "estimated_cost_nano_usd", "usage_count",
    "priced_usage_count", "unpriced_usage_count", "counter_value", "metric_value", "priced_token_total",
    "unpriced_token_total", "mixed_price_token_total", "quality_count", "unknown_count", "row_count",
    "observed_seconds", "working_seconds", "running_seconds", "starts", "completions",
    "waiting_seconds", "subagent_seconds", "global_observed_seconds")
SPREAD_STEPS = {"minute": 60, "5minute": 300}


def _share(value: Any, index: int, parts: int) -> Any:
    if value is None or parts == 1:
        return value
    if isinstance(value, int):
        base, extra = divmod(value, parts)
        return base + (1 if index < extra else 0)
    each = value / parts
    return value - each * (parts - 1) if index == parts - 1 else each


def spread_hours(rows: List[Any], step: int, end: int, *, source_grain: int = GRAIN_HOUR) -> List[Any]:
    if source_grain <= step:
        return list(rows)
    out: List[Any] = []
    max_parts = max(1, source_grain // step)
    for row in rows:
        keys = row.keys()
        bucket_start = row["minute_ts"]
        parts = max(1, min(max_parts, -(-(end - bucket_start) // step)))
        measures = [name for name in _SPREAD_FIELDS if name in keys]
        for index in range(parts):
            part = {name: row[name] for name in keys}
            part["minute_ts"] = bucket_start + index * step
            for name in measures:
                part[name] = _share(row[name], index, parts)
            if "row_count" in part and part["row_count"] is not None:
                part["row_count"] = max(1, part["row_count"])
            out.append(part)
    return out


spread_rows = spread_hours


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def roster_view() -> Tuple[str, Dict[str, bool]]:
    from src.core.pack.machines import roster as roster_mod, runtime

    wired = runtime.wiring()
    if wired is None:
        return "this computer", {}
    online = {}
    for peer in wired.peers():
        state = wired.runtime.roster.peer_state(peer)
        online[peer.install_id] = state in (roster_mod.STATE_CONNECTED, roster_mod.STATE_WAITING, roster_mod.STATE_OLDER)
    paired = {peer.install_id for peer in wired.peers()}
    roster = wired.runtime.roster
    for entry in list(roster.entries.values()):
        if roster.fresh(entry):
            for member in entry.members:
                if member["install_id"] not in paired and member.get("state") == "connected":
                    online[member["install_id"]] = True
    return wired.runtime.label or "this computer", online


def computers(store: Any, self_label: str, online: Dict[str, bool]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = [{"id": LOCAL, "label": self_label, "self": True, "online": True, "through": None}]
    app = _open_app(store)
    if app is None:
        return out
    with closing(app):
        try:
            labels = {r[0]: r[1] for r in app.execute(
                "SELECT peer_install_id, label FROM hosts WHERE peer_install_id IS NOT NULL AND peer_install_id != ''")}
            for peer, pulled, via, state_label, origin_pulled in app.execute(
                    f"SELECT peer_install_id, pulled_at, via, label, origin_pulled_at FROM {STATE_TABLE} ORDER BY peer_install_id"):
                newest = app.execute(f"SELECT MAX(hour) FROM {USAGE_TABLE} WHERE peer_install_id = ?", (peer,)).fetchone()[0]
                relayed = via != ""
                up = online.get(peer, not relayed)
                seen = origin_pulled if relayed else pulled
                through = None
                if not up and newest is not None:
                    through = _iso(min(newest + 3600, seen) if seen else newest + 3600)
                out.append({"id": peer, "label": labels.get(peer) or state_label or peer[:8], "self": False, "online": up, "through": through})
        except sqlite3.Error as exc:
            _warn_unreadable(exc)
    return out


_groups_lock = threading.Lock()
_groups_cache: Dict[str, Tuple[Tuple[int, str], ProjectGroups]] = {}


def pack_groups(store: Any, groups: ProjectGroups) -> ProjectGroups:
    app = _open_app(store)
    if app is None:
        return groups
    with closing(app):
        try:
            rows = [(r[0], r[1], r[2]) for r in app.execute(f"SELECT peer_install_id, project, name FROM {PROJECTS_TABLE} ORDER BY project, peer_install_id")]
        except sqlite3.Error as exc:
            _warn_unreadable(exc)
            return groups
    if not rows:
        return groups
    key = (id(groups), digest(rows))
    with _groups_lock:
        hit = _groups_cache.get(str(store.state_dir))
    if hit is not None and hit[0] == key:
        return hit[1]
    out = ProjectGroups(group=dict(groups.group), labels=dict(groups.labels), folders=dict(groups.folders))
    local_by_name: Dict[str, str] = {}
    for group_key in sorted(groups.labels):
        local_by_name.setdefault(groups.labels[group_key].strip().casefold(), group_key)
    peer_by_name: Dict[str, str] = {}
    for _origin, project, name in rows:
        if project in groups.group:
            continue
        folded = name.strip().casefold()
        target = local_by_name.get(folded) or peer_by_name.setdefault(folded, project)
        out.group[project] = target
        if target == project:
            out.labels.setdefault(project, name)
    with _groups_lock:
        _groups_cache[str(store.state_dir)] = (key, out)
    return out


def host_dimension(store: Any, self_label: str, online: Dict[str, bool]) -> Dict[str, Any]:
    items = [{"key": c["id"], "label": c["label"], "filter_value": c["id"], "minute_rows": 0} for c in computers(
        store, self_label, online)]
    return {"items": items, "next_cursor": None, "total": len(items)}


def annotate(store: Any, results: List[Dict[str, Any]], online: Dict[str, bool], self_label: str) -> List[Dict[str, Any]]:
    if not any(r.get("ok") and r["result"].get("scope") == "pack" for r in results):
        return results
    offline = [{"id": c["id"], "label": c["label"], "through": c["through"]}
               for c in computers(store, self_label, online) if not c["online"] and c["through"]]
    return [({**r, "result": {**r["result"], "pack": {"offline": offline}}}
             if r.get("ok") and r["result"].get("scope") == "pack" else r) for r in results]

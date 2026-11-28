
from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple

import structlog

from src.core.pack.machines.settings_sign import Signing, signature_from
from src.core.pack.meshdata import envelope
from src.core.stats import agent_names

logger = structlog.get_logger()

V2_KEY = "v2"
MAX_V2_BYTES = 350 * 1024
MAX_CONV_META = 5000
MAX_USAGE_5M = 2000
MAX_ACTIVITY = 2000
MAX_QUOTA = 1500
MAX_CONVERSATIONS = 500
MAX_EVENTS = 200
MAX_MCP = 1000
MAX_EVENT_DATA_BYTES = 512

_SECONDS_24H = 86400
_SECONDS_30D = 30 * 86400
_SAFE_ID = re.compile(r"[A-Za-z0-9_.:@=/-]{1,128}")


def _epoch_valid(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2 ** 62 else None


def _project_allowed(project: str, allow_projects: Optional[FrozenSet[str]], revoked_projects: FrozenSet[str]) -> bool:
    if project in revoked_projects:
        return False
    if allow_projects is not None:
        return project in allow_projects
    return True


def _tables_in(conn: sqlite3.Connection) -> FrozenSet[str]:
    return frozenset(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"))


def _parse_epoch(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return None


def _clean_event_data(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return "{}"
    try:
        parsed = json.loads(raw)
    except ValueError:
        return "{}"
    if not isinstance(parsed, dict):
        return "{}"
    out: Dict[str, Any] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not _SAFE_ID.fullmatch(key):
            continue
        if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, str) and _SAFE_ID.fullmatch(value):
            out[key] = value
    text = json.dumps(out, separators=(",", ":"), sort_keys=True)
    return text if len(text) <= MAX_EVENT_DATA_BYTES else "{}"


def _split_mcp_tool(raw_tool: str) -> Tuple[str, str]:
    if raw_tool.startswith("mcp__"):
        parts = raw_tool.split("__", 2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return parts[1][:128], parts[2][:128]
    return "carnivore", raw_tool[:128]


def stats_revision(store: Any) -> int:
    if store is None:
        return 0
    try:
        with store.connect() as conn:
            row = conn.execute("SELECT value FROM stats_meta WHERE key = 'revision'").fetchone()
            return int(row[0]) if row is not None else 0
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        return 0


def _export_conv_meta(
    conn: sqlite3.Connection,
    tables: FrozenSet[str],
    allow_projects: Optional[FrozenSet[str]],
    revoked_projects: FrozenSet[str],
) -> Dict[str, List[str]]:
    if "dim_source" not in tables:
        return {}
    allowed_convs: Optional[set[str]] = None
    if allow_projects is not None or revoked_projects:
        by_conv: Dict[str, set[str]] = {}
        if "dim_project" in tables:
            for tbl in ("usage_hour", "usage_minute"):
                if tbl not in tables:
                    continue
                for cid, proj in conn.execute(
                    f"SELECT DISTINCT s.conversation_id, p.name FROM {tbl} u "
                    "JOIN dim_source s ON s.id = u.src JOIN dim_project p ON p.id = u.project"
                ):
                    by_conv.setdefault(str(cid), set()).add(str(proj))
        allowed_convs = {
            cid for cid, projs in by_conv.items()
            if projs and all(_project_allowed(p, allow_projects, revoked_projects) for p in projs)
        }
        if not allowed_convs:
            return {}
    out: Dict[str, List[str]] = {}
    for cid, acct, stype in conn.execute(
        "SELECT conversation_id, COALESCE(NULLIF(MAX(account_id), ''), 'unknown'), "
        "COALESCE(NULLIF(MAX(subagent_type), ''), 'unknown') "
        "FROM dim_source GROUP BY conversation_id "
        "ORDER BY COALESCE(MAX(last_minute), 0) DESC, conversation_id ASC"
    ):
        cid_s = str(cid)
        if not cid_s or (allowed_convs is not None and cid_s not in allowed_convs):
            continue
        out[cid_s] = [str(acct or "unknown")[:128], str(stype or "unknown")[:128]]
        if len(out) >= MAX_CONV_META:
            break
    return out


def _export_usage_5m(
    conn: sqlite3.Connection,
    tables: FrozenSet[str],
    cutoff_24h: int,
    allow_projects: Optional[FrozenSet[str]],
    revoked_projects: FrozenSet[str],
    names: Dict[str, str],
) -> List[List[Any]]:
    required = {"usage_minute", "dim_source", "dim_model", "dim_project"}
    if not required.issubset(tables):
        return []
    rows = conn.execute(
        "SELECT s.conversation_id, (u.t / 300) * 300 AS bucket_5m, "
        "MIN(s.provider), MIN(s.agent_kind), m.name, p.name, "
        "COALESCE(NULLIF(MAX(s.account_id), ''), 'unknown'), "
        "COALESCE(NULLIF(MAX(s.subagent_type), ''), 'unknown'), "
        "SUM(u.input), SUM(u.cache_write), SUM(u.cache_read), SUM(u.output), "
        "COALESCE(SUM(u.cost_nano), 0), SUM(u.messages), SUM(u.priced) "
        "FROM usage_minute u "
        "JOIN dim_source s ON s.id = u.src "
        "JOIN dim_model m ON m.id = u.model "
        "JOIN dim_project p ON p.id = u.project "
        "WHERE u.t >= ? "
        "GROUP BY s.conversation_id, bucket_5m, m.name, p.name "
        "ORDER BY bucket_5m DESC, s.conversation_id ASC, m.name ASC, p.name ASC",
        (cutoff_24h,),
    ).fetchall()
    kept: List[List[Any]] = []
    for r in rows:
        proj = str(r[5])
        if not _project_allowed(proj, allow_projects, revoked_projects):
            continue
        cid = str(r[0])
        aname = names.get(agent_names.root_of(cid))
        kept.append([
            cid, int(r[1]), r[2], r[3], str(r[4]), proj, str(r[6]), str(r[7]),
            int(r[8]), int(r[9]), int(r[10]), int(r[11]), int(r[12]), int(r[13]), int(r[14]), aname,
        ])
        if len(kept) >= MAX_USAGE_5M:
            break
    kept.sort(key=lambda item: (item[1], item[0], item[4], item[5]))
    return kept


def _export_activity(
    conn: sqlite3.Connection,
    tables: FrozenSet[str],
    cutoff_30d: int,
    cutoff_24h: int,
    allow_projects: Optional[FrozenSet[str]],
    revoked_projects: FrozenSet[str],
) -> List[List[Any]]:
    if "dim_live" not in tables:
        return []
    cov_hour: Dict[int, int] = {}
    if "coverage_hour" in tables:
        for t, obs in conn.execute("SELECT t, observed FROM coverage_hour WHERE t >= ?", (cutoff_30d,)):
            cov_hour[int(t)] = int(round(min(3600.0, float(obs or 0))))
    cov_5m: Dict[int, int] = {}
    if "coverage_minute" in tables:
        for b, obs in conn.execute(
            "SELECT (t / 300) * 300 AS b, SUM(observed) FROM coverage_minute WHERE t >= ? GROUP BY b",
            (cutoff_24h,),
        ):
            cov_5m[int(b)] = int(round(min(300.0, float(obs or 0))))

    out: List[List[Any]] = []
    specs = (
        ("activity_hour", 3600, cutoff_30d, "a.t", cov_hour),
        ("activity_minute", 300, cutoff_24h, "(a.t / 300) * 300", cov_5m),
    )
    for table, grain, cutoff, bucket_expr, cov_map in specs:
        if table not in tables:
            continue
        rows = conn.execute(
            f"SELECT d.conversation_id, {bucket_expr} AS bucket_ts, "
            "MIN(d.provider), MIN(d.agent_kind), MIN(d.model), d.project, "
            "SUM(a.observed), SUM(a.working), SUM(a.running), "
            "SUM(a.starts), SUM(a.completions), SUM(a.waiting), SUM(a.subagent) "
            f"FROM {table} a JOIN dim_live d ON d.id = a.live "
            "WHERE a.t >= ? "
            "GROUP BY d.conversation_id, bucket_ts, d.project "
            "ORDER BY bucket_ts DESC, d.conversation_id ASC, d.project ASC",
            (cutoff,),
        ).fetchall()
        for r in rows:
            proj = str(r[5] or "")
            if not _project_allowed(proj, allow_projects, revoked_projects):
                continue
            bts = int(r[1])
            out.append([
                str(r[0]), bts, grain, r[2], r[3], str(r[4] or ""), proj,
                int(round(float(r[6] or 0))), int(round(float(r[7] or 0))),
                int(round(float(r[8] or 0))), int(r[9] or 0), int(r[10] or 0),
                int(round(float(r[11] or 0))), int(round(float(r[12] or 0))),
                cov_map.get(bts, 0),
            ])
    out.sort(key=lambda item: (-item[1], item[2], item[0], item[6]))
    out = out[:MAX_ACTIVITY]
    out.sort(key=lambda item: (item[2], item[1], item[0], item[6]))
    return out


def _export_quota(
    conn: sqlite3.Connection,
    tables: FrozenSet[str],
    cutoff_30d: int,
    cutoff_24h: int,
) -> List[List[Any]]:
    out: List[List[Any]] = []
    specs = (("quota_hour", 3600, cutoff_30d, "t"), ("quota_minute", 300, cutoff_24h, "(t / 300) * 300"))
    for table, grain, cutoff, bucket_expr in specs:
        if table not in tables:
            continue
        by_key: Dict[Tuple[int, str, str, str], Tuple[Optional[float], Optional[int], str, int]] = {}
        for r in conn.execute(
            f"SELECT {bucket_expr} AS bucket_ts, provider, account_id, window, utilization, fetched_at, state "
            f"FROM {table} WHERE t >= ? ORDER BY bucket_ts ASC, fetched_at ASC",
            (cutoff,),
        ):
            key = (int(r[0]), str(r[1]), str(r[2]), str(r[3]))
            util = None if r[4] is None else float(r[4])
            fetched = _parse_epoch(r[5])
            state = str(r[6] or "ok")[:32]
            hit = 1 if (util is not None and util >= 100.0) or state == "limit_hit" else 0
            prev = by_key.get(key)
            if prev is None or (fetched or 0) >= (prev[1] or 0):
                by_key[key] = (util, fetched, state, max(hit, prev[3] if prev is not None else 0))
        for (bts, provider, acct, window), (util, fetched, state, hit) in by_key.items():
            out.append([bts, grain, provider, acct, window, util, fetched, state, hit])
    out.sort(key=lambda item: (-item[0], item[1], item[2], item[3], item[4]))
    out = out[:MAX_QUOTA]
    out.sort(key=lambda item: (item[1], item[0], item[2], item[3], item[4]))
    return out


def _export_conversations(
    conn: sqlite3.Connection,
    tables: FrozenSet[str],
    allow_projects: Optional[FrozenSet[str]],
    revoked_projects: FrozenSet[str],
    names: Dict[str, str],
) -> List[List[Any]]:
    required = {"usage_hour", "dim_source", "dim_model", "dim_project"}
    if not required.issubset(tables):
        return []
    turns_by_conv: Dict[str, int] = {}
    if {"counter_hour", "dim_counter"}.issubset(tables):
        for cid, val in conn.execute(
            "SELECT s.conversation_id, SUM(c.value) FROM counter_hour c "
            "JOIN dim_source s ON s.id = c.src JOIN dim_counter n ON n.id = c.counter "
            "WHERE n.name = 'turns' GROUP BY s.conversation_id"
        ):
            turns_by_conv[str(cid)] = int(val or 0)
    per: Dict[str, Dict[str, Any]] = {}
    rows = conn.execute(
        "SELECT s.conversation_id, p.name, m.name, MIN(s.provider), MIN(s.agent_kind), "
        "COALESCE(NULLIF(MAX(s.account_id), ''), 'unknown'), "
        "COALESCE(NULLIF(MAX(s.subagent_type), ''), 'unknown'), "
        "MIN(COALESCE(s.first_minute, u.t)), MAX(COALESCE(s.last_minute, u.t)), "
        "SUM(u.input + u.cache_write + u.cache_read + u.output), "
        "SUM(u.cost_nano), SUM(u.messages), SUM(u.priced) "
        "FROM usage_hour u "
        "JOIN dim_source s ON s.id = u.src "
        "JOIN dim_model m ON m.id = u.model "
        "JOIN dim_project p ON p.id = u.project "
        "GROUP BY s.conversation_id, p.name, m.name"
    ).fetchall()
    for r in rows:
        proj = str(r[1])
        if not _project_allowed(proj, allow_projects, revoked_projects):
            continue
        cid = str(r[0])
        tokens = int(r[9] or 0)
        cost = None if r[10] is None and int(r[12] or 0) == 0 else int(r[10] or 0)
        entry = per.get(cid)
        if entry is None:
            per[cid] = {
                "project": proj, "model": str(r[2]), "provider": r[3], "agent_kind": r[4],
                "account_id": str(r[5]), "subagent_type": str(r[6]),
                "started_at": int(r[7] or 0), "ended_at": int(r[8] or 0),
                "tokens": tokens, "cost_nano": cost, "messages": int(r[11] or 0), "top": tokens,
            }
        else:
            entry["tokens"] += tokens
            entry["messages"] += int(r[11] or 0)
            entry["started_at"] = min(entry["started_at"], int(r[7] or 0))
            entry["ended_at"] = max(entry["ended_at"], int(r[8] or 0))
            if cost is not None:
                entry["cost_nano"] = (entry["cost_nano"] or 0) + cost
            if tokens > entry["top"]:
                entry["top"], entry["project"], entry["model"] = tokens, proj, str(r[2])
    ordered = sorted(
        per.items(),
        key=lambda kv: (-(kv[1]["cost_nano"] or 0), -kv[1]["ended_at"], -kv[1]["tokens"], kv[0]),
    )[:MAX_CONVERSATIONS]
    out: List[List[Any]] = []
    for cid, e in ordered:
        aname = names.get(agent_names.root_of(cid))
        turns = turns_by_conv.get(cid, e["messages"])
        out.append([
            cid, e["project"], e["model"], e["provider"], e["agent_kind"],
            e["account_id"], e["subagent_type"], aname,
            e["started_at"], e["ended_at"], e["tokens"], e["cost_nano"], int(turns), None,
        ])
    return out


def _export_events(conn: sqlite3.Connection, tables: FrozenSet[str]) -> List[List[Any]]:
    if "stats_events" not in tables:
        return []
    rows = conn.execute(
        "SELECT id, occurred_at, kind, subject, data FROM stats_events "
        "ORDER BY occurred_at DESC, id DESC LIMIT ?",
        (MAX_EVENTS,),
    ).fetchall()
    out: List[List[Any]] = []
    for r in rows:
        out.append([
            str(r[0]), int(r[1]), str(r[2])[:64], str(r[3] or "")[:128], _clean_event_data(r[4]),
        ])
    return out


def _export_coverage(conn: sqlite3.Connection, tables: FrozenSet[str], store: Any) -> Dict[str, Any]:
    earliest: Optional[int] = None
    latest: Optional[int] = None
    minute_rows = 0
    unknown_cost = 0
    if "usage_hour" in tables and "usage_minute" in tables:
        floor = 0
        if "stat_retention" in tables:
            row = conn.execute("SELECT minute_floor FROM stat_retention WHERE singleton = 1").fetchone()
            floor = int(row[0]) if row is not None else 0
        row = conn.execute(
            "SELECT MIN(t), MAX(t), COUNT(*), COALESCE(SUM(cost_nano IS NULL), 0) FROM ("
            "SELECT t, cost_nano FROM usage_minute WHERE t >= ? "
            "UNION ALL "
            "SELECT t, cost_nano FROM usage_hour WHERE t < ?)",
            (floor, floor),
        ).fetchone()
        if row is not None:
            earliest = int(row[0]) if row[0] is not None else None
            latest = int(row[1]) if row[1] is not None else None
            minute_rows = int(row[2] or 0)
            unknown_cost = int(row[3] or 0)
    tracked_sources = 0
    if "plugin_cursors" in tables:
        tracked_sources = int(conn.execute("SELECT COUNT(*) FROM plugin_cursors").fetchone()[0])
    elif "dim_source" in tables:
        tracked_sources = int(conn.execute("SELECT COUNT(*) FROM dim_source").fetchone()[0])
    db_bytes = 0
    db_path = getattr(store, "db_path", None)
    if db_path is not None:
        p = Path(db_path)
        for candidate in (p, p.with_name(p.name + "-wal")):
            try:
                if candidate.exists():
                    db_bytes += int(candidate.stat().st_size)
            except OSError:
                continue
    return {
        "earliest_ts": earliest,
        "latest_ts": latest,
        "minute_rows": minute_rows,
        "unknown_cost_rows": unknown_cost,
        "tracked_sources": tracked_sources,
        "db_bytes": db_bytes,
    }


def _export_mcp(open_app: Callable[[], sqlite3.Connection], cutoff_30d: int) -> List[List[Any]]:
    try:
        with closing(open_app()) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'mcp_events'").fetchone() is None:
                return []
            agg: Dict[Tuple[int, str, str], List[int]] = {}
            for hr, raw_tool, calls, errs, total_ms in conn.execute(
                "SELECT (CAST(started_at AS INTEGER) / 3600) * 3600 AS hr, tool, "
                "COUNT(*), SUM(CASE WHEN outcome IN ('error', 'denied') THEN 1 ELSE 0 END), "
                "COALESCE(SUM(duration_ms), 0) "
                "FROM mcp_events WHERE started_at >= ? GROUP BY hr, tool",
                (float(cutoff_30d),),
            ):
                server, tool = _split_mcp_tool(str(raw_tool or ""))
                if not tool:
                    continue
                key = (int(hr), server, tool)
                cur = agg.get(key)
                if cur is None:
                    agg[key] = [int(calls or 0), int(errs or 0), int(total_ms or 0)]
                else:
                    cur[0] += int(calls or 0)
                    cur[1] += int(errs or 0)
                    cur[2] += int(total_ms or 0)
    except sqlite3.Error as exc:
        logger.info("pack_rollup_v2_mcp_unreadable", error_type=type(exc).__name__)
        return []
    out = [[hr, srv, tool, vals[0], vals[1], vals[2]] for (hr, srv, tool), vals in agg.items()]
    out.sort(key=lambda item: (-item[0], item[1], item[2]))
    out = out[:MAX_MCP]
    out.sort(key=lambda item: (item[0], item[1], item[2]))
    return out


def _canonical_size(payload: Dict[str, Any]) -> int:
    return len(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"))


def _bound_payload(payload: Dict[str, Any], max_bytes: int = MAX_V2_BYTES) -> Dict[str, Any]:
    if _canonical_size(payload) <= max_bytes:
        return payload
    trimmed = {k: (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v)) for k, v in payload.items()}
    list_sections = (
        ("usage_5m", True),
        ("activity", True),
        ("quota", True),
        ("mcp", True),
        ("events", False),
        ("conversations", False),
    )
    while _canonical_size(trimmed) > max_bytes:
        progressed = False
        for key, drop_head in list_sections:
            items = trimmed.get(key)
            if isinstance(items, list) and items:
                cut = max(1, len(items) // 4)
                trimmed[key] = items[cut:] if drop_head else items[:-cut]
                progressed = True
                if _canonical_size(trimmed) <= max_bytes:
                    return trimmed
        if not progressed:
            cm = trimmed.get("conv_meta")
            if isinstance(cm, dict) and cm:
                keep = sorted(cm.keys())[: max(0, len(cm) - max(1, len(cm) // 4))]
                trimmed["conv_meta"] = {k: cm[k] for k in keep}
            else:
                break
    return trimmed


def build_v2(
    store: Any,
    open_app: Callable[[], sqlite3.Connection],
    *,
    allow_projects: Optional[FrozenSet[str]] = None,
    revoked_projects: FrozenSet[str] = frozenset(),
    now: Optional[float] = None,
    max_bytes: int = MAX_V2_BYTES,
) -> Dict[str, Any]:
    now_ts = int(time.time() if now is None else now)
    cutoff_24h = now_ts - _SECONDS_24H
    cutoff_30d = now_ts - _SECONDS_30D
    try:
        names = agent_names.local_names(store)
    except Exception as exc:  # noqa: BLE001
        logger.info("pack_rollup_v2_names_unreadable", error_type=type(exc).__name__)
        names = {}

    conv_meta: Dict[str, List[str]] = {}
    usage_5m: List[List[Any]] = []
    activity: List[List[Any]] = []
    quota: List[List[Any]] = []
    conversations: List[List[Any]] = []
    events: List[List[Any]] = []
    coverage: Dict[str, Any] = {
        "earliest_ts": None, "latest_ts": None, "minute_rows": 0,
        "unknown_cost_rows": 0, "tracked_sources": 0, "db_bytes": 0,
    }
    try:
        with store.connect() as conn:
            tables = _tables_in(conn)
            conv_meta = _export_conv_meta(conn, tables, allow_projects, revoked_projects)
            usage_5m = _export_usage_5m(conn, tables, cutoff_24h, allow_projects, revoked_projects, names)
            activity = _export_activity(conn, tables, cutoff_30d, cutoff_24h, allow_projects, revoked_projects)
            quota = _export_quota(conn, tables, cutoff_30d, cutoff_24h)
            conversations = _export_conversations(conn, tables, allow_projects, revoked_projects, names)
            events = _export_events(conn, tables)
            coverage = _export_coverage(conn, tables, store)
    except sqlite3.Error as exc:
        logger.info("pack_rollup_v2_stats_unreadable", error_type=type(exc).__name__)

    mcp = _export_mcp(open_app, cutoff_30d)
    payload: Dict[str, Any] = {
        "conv_meta": conv_meta,
        "usage_5m": usage_5m,
        "activity": activity,
        "quota": quota,
        "conversations": conversations,
        "events": events,
        "coverage": coverage,
        "mcp": mcp,
    }
    return _bound_payload(payload, max_bytes=max_bytes)


def v2_body(payload: Dict[str, Any], epoch: int) -> Dict[str, Any]:
    return {"v2": payload, "e": epoch}


def sign_v2(payload: Dict[str, Any], stamp: int, signing: Signing, epoch: int) -> Optional[Dict[str, Any]]:
    sig = envelope.try_sign(
        envelope.KIND_ROLLUP_V2, V2_KEY, stamp, envelope.body_hash(v2_body(payload, epoch)), signing
    )
    if sig is None:
        return None
    return {"v2": payload, "v2_rev": stamp, "v2_epoch": epoch, "v2_sig": sig.to_dict()}


def verify_v2(
    origin: str,
    payload: Any,
    stamp: Any,
    sig_raw: Any,
    lst: Any,
    epoch: Any,
) -> Optional[Tuple[int, str, int]]:
    sig = signature_from(sig_raw)
    valid_epoch = _epoch_valid(epoch)
    if (
        sig is None
        or valid_epoch is None
        or not isinstance(stamp, int)
        or isinstance(stamp, bool)
        or stamp < 0
        or not isinstance(payload, dict)
    ):
        return None
    if not envelope.verify(
        envelope.KIND_ROLLUP_V2, origin, V2_KEY, stamp, envelope.body_hash(v2_body(payload, valid_epoch)), sig, lst
    ):
        return None
    return stamp, sig.sig, valid_epoch

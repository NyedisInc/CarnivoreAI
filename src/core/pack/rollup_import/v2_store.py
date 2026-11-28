
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import structlog

from src.core.pack.rollup_import import relay_store
from src.core.pack.rollup_import.ddl import (
    ACTIVITY_TABLE,
    CONVERSATIONS_TABLE,
    COVERAGE_TABLE,
    EVENTS_TABLE,
    MCP_TABLE,
    QUOTA_TABLE,
    STATE_TABLE,
    USAGE_5M_TABLE,
    USAGE_TABLE,
    V2_FLOOR_KEY,
    V2_ORIGIN_TABLES,
)
from src.core.pack.rollup_import.v2_export import (
    MAX_ACTIVITY,
    MAX_CONV_META,
    MAX_CONVERSATIONS,
    MAX_EVENT_DATA_BYTES,
    MAX_EVENTS,
    MAX_MCP,
    MAX_QUOTA,
    MAX_USAGE_5M,
)

logger = structlog.get_logger()

RETENTION_5M_SECONDS = 26 * 3600
_MAX_ID = 256
_MAX_TEXT = 200
_noted: set[str] = set()


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _str_or_none(v: Any, limit: int = _MAX_TEXT) -> Optional[str]:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s[:limit] if s else None


def _req_str(v: Any, limit: int = _MAX_ID) -> Optional[str]:
    return v if isinstance(v, str) and 0 < len(v) <= limit else None


def _opt_str(v: Any, limit: int = _MAX_ID) -> Optional[str]:
    return v if isinstance(v, str) and len(v) <= limit else None


def _clean_conv_meta(raw: Any) -> Optional[Dict[str, Tuple[str, str]]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Tuple[str, str]] = {}
    for cid, val in raw.items():
        if len(out) >= MAX_CONV_META:
            break
        if _req_str(cid, _MAX_ID) is None or not isinstance(val, (list, tuple)) or len(val) != 2:
            continue
        acct = _str_or_none(val[0], 128) or "unknown"
        stype = _str_or_none(val[1], 128) or "unknown"
        out[cid] = (acct, stype)
    return out


def _clean_usage_5m(raw: Any) -> Optional[List[tuple]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    out: List[tuple] = []
    for row in raw[:MAX_USAGE_5M]:
        if not isinstance(row, (list, tuple)) or len(row) != 16:
            return None
        cid, b5, prov, ak, model, proj, acct, stype = row[:8]
        nums = row[8:15]
        aname = row[15]
        if (
            _req_str(cid) is None
            or not _is_int(b5)
            or _req_str(model) is None
            or _req_str(proj) is None
            or not all(_is_int(x) for x in nums)
        ):
            return None
        out.append((
            cid, int(b5), _str_or_none(prov, 64), _str_or_none(ak, 64), model, proj,
            _str_or_none(acct, 128) or "unknown", _str_or_none(stype, 128) or "unknown",
            int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3]), int(nums[4]), int(nums[5]), int(nums[6]),
            _str_or_none(aname, _MAX_TEXT),
        ))
    return out


def _clean_activity(raw: Any) -> Optional[List[tuple]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    out: List[tuple] = []
    for row in raw[:MAX_ACTIVITY]:
        if not isinstance(row, (list, tuple)) or len(row) != 15:
            return None
        cid, bts, grain, prov, ak, model, proj = row[:7]
        nums = row[7:15]
        if (
            _req_str(cid) is None
            or not _is_int(bts)
            or grain not in (300, 3600)
            or _opt_str(model) is None
            or _opt_str(proj) is None
            or not all(_is_int(x) for x in nums)
        ):
            return None
        out.append((
            cid, int(bts), int(grain), _str_or_none(prov, 64), _str_or_none(ak, 64),
            str(model), str(proj),
            *(int(x) for x in nums),
        ))
    return out


def _clean_quota(raw: Any) -> Optional[List[tuple]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    out: List[tuple] = []
    for row in raw[:MAX_QUOTA]:
        if not isinstance(row, (list, tuple)) or len(row) != 9:
            return None
        bts, grain, prov, acct, window, util, fetched, state, hit = row
        if (
            not _is_int(bts)
            or grain not in (300, 3600)
            or _req_str(prov, 64) is None
            or _req_str(acct, 128) is None
            or _req_str(window, 64) is None
            or (util is not None and not _is_num(util))
            or (fetched is not None and not _is_int(fetched))
            or not _is_int(hit)
        ):
            return None
        out.append((
            int(bts), int(grain), prov, acct, window,
            None if util is None else float(util),
            None if fetched is None else int(fetched),
            _str_or_none(state, 32) or "ok",
            1 if int(hit) else 0,
        ))
    return out


def _clean_conversations(raw: Any) -> Optional[List[tuple]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    out: List[tuple] = []
    for row in raw[:MAX_CONVERSATIONS]:
        if not isinstance(row, (list, tuple)) or len(row) != 14:
            return None
        cid, proj, model, prov, ak, acct, stype, aname, start, end, tokens, cost, turns, impact = row
        if (
            _req_str(cid) is None
            or _opt_str(proj) is None
            or _opt_str(model) is None
            or not (_is_int(start) and _is_int(end) and _is_int(tokens) and _is_int(turns))
            or (cost is not None and not _is_int(cost))
            or (impact is not None and not _is_num(impact))
        ):
            return None
        out.append((
            cid, str(proj), str(model), _str_or_none(prov, 64), _str_or_none(ak, 64),
            _str_or_none(acct, 128) or "unknown", _str_or_none(stype, 128) or "unknown",
            _str_or_none(aname, _MAX_TEXT), int(start), int(end), int(tokens),
            None if cost is None else int(cost), int(turns),
            None if impact is None else float(impact),
        ))
    return out


def _clean_events(raw: Any) -> Optional[List[tuple]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    out: List[tuple] = []
    for row in raw[:MAX_EVENTS]:
        if not isinstance(row, (list, tuple)) or len(row) != 5:
            return None
        eid, ts, kind, subject, data = row
        if (
            _req_str(eid, 128) is None
            or not _is_int(ts)
            or _req_str(kind, 64) is None
            or _opt_str(subject, 128) is None
            or not isinstance(data, str)
            or len(data) > MAX_EVENT_DATA_BYTES
        ):
            return None
        out.append((eid, int(ts), kind, str(subject), data))
    return out


def _clean_coverage(raw: Any) -> Optional[Optional[tuple]]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    earliest = raw.get("earliest_ts")
    latest = raw.get("latest_ts")
    mrows = raw.get("minute_rows", 0)
    unk = raw.get("unknown_cost_rows", 0)
    sources = raw.get("tracked_sources", 0)
    db_bytes = raw.get("db_bytes", 0)
    if (
        (earliest is not None and not _is_int(earliest))
        or (latest is not None and not _is_int(latest))
        or not all(_is_int(x) for x in (mrows, unk, sources, db_bytes))
    ):
        return None
    return (
        None if earliest is None else int(earliest),
        None if latest is None else int(latest),
        int(mrows), int(unk), int(sources), int(db_bytes),
    )


def _clean_mcp(raw: Any) -> Optional[List[tuple]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    out: List[tuple] = []
    for row in raw[:MAX_MCP]:
        if not isinstance(row, (list, tuple)) or len(row) != 6:
            return None
        hr, server, tool, calls, errs, total_ms = row
        if (
            not _is_int(hr)
            or _req_str(server, 128) is None
            or _req_str(tool, 128) is None
            or not (_is_int(calls) and _is_int(errs) and _is_int(total_ms))
        ):
            return None
        out.append((int(hr), server, tool, int(calls), int(errs), int(total_ms)))
    return out


def validate_v2(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    conv_meta = _clean_conv_meta(raw.get("conv_meta"))
    usage_5m = _clean_usage_5m(raw.get("usage_5m"))
    activity = _clean_activity(raw.get("activity"))
    quota = _clean_quota(raw.get("quota"))
    conversations = _clean_conversations(raw.get("conversations"))
    events = _clean_events(raw.get("events"))
    mcp = _clean_mcp(raw.get("mcp"))
    if any(x is None for x in (conv_meta, usage_5m, activity, quota, conversations, events, mcp)):
        return None
    cov_raw = raw.get("coverage")
    coverage = None if cov_raw is None else _clean_coverage(cov_raw)
    if cov_raw is not None and coverage is None:
        return None
    return {
        "conv_meta": conv_meta,
        "usage_5m": usage_5m,
        "activity": activity,
        "quota": quota,
        "conversations": conversations,
        "events": events,
        "coverage": coverage,
        "mcp": mcp,
    }


def v2_projects(payload: Dict[str, Any]) -> FrozenSet[str]:
    found: set[str] = set()
    for row in payload.get("usage_5m") or ():
        if isinstance(row, (list, tuple)) and len(row) > 5 and isinstance(row[5], str) and row[5]:
            found.add(row[5])
    for row in payload.get("activity") or ():
        if isinstance(row, (list, tuple)) and len(row) > 6 and isinstance(row[6], str) and row[6]:
            found.add(row[6])
    for row in payload.get("conversations") or ():
        if isinstance(row, (list, tuple)) and len(row) > 1 and isinstance(row[1], str) and row[1]:
            found.add(row[1])
    return frozenset(found)


def apply_v2(
    conn: sqlite3.Connection,
    origin: str,
    payload: Any,
    *,
    rev: Optional[int] = None,
    now: Optional[float] = None,
) -> bool:
    cleaned = validate_v2(payload)
    if cleaned is None:
        return False
    now_f = time.time() if now is None else float(now)
    prune_cutoff = int(now_f) - RETENTION_5M_SECONDS

    for table in V2_ORIGIN_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE peer_install_id = ?", (origin,))

    usage_5m_rows = [(origin, *r) for r in cleaned["usage_5m"] if r[1] >= prune_cutoff]
    if usage_5m_rows:
        conn.executemany(
            f"INSERT OR REPLACE INTO {USAGE_5M_TABLE} ("
            "peer_install_id, conversation_id, bucket_5m, provider, agent_kind, model, project, "
            "account_id, subagent_type, input, cache_write, cache_read, output, cost_nano, "
            "messages, priced, agent_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            usage_5m_rows,
        )

    activity_rows = [(origin, *r) for r in cleaned["activity"] if not (r[2] == 300 and r[1] < prune_cutoff)]
    if activity_rows:
        conn.executemany(
            f"INSERT OR REPLACE INTO {ACTIVITY_TABLE} ("
            "peer_install_id, conversation_id, bucket_ts, grain, provider, agent_kind, model, project, "
            "observed_seconds, working_seconds, running_seconds, starts, completions, waiting_seconds, "
            "subagent_seconds, global_observed_seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            activity_rows,
        )

    quota_rows = [(origin, *r) for r in cleaned["quota"] if not (r[1] == 300 and r[0] < prune_cutoff)]
    if quota_rows:
        conn.executemany(
            f"INSERT OR REPLACE INTO {QUOTA_TABLE} ("
            "peer_install_id, bucket_ts, grain, provider, account_id, window, utilization, fetched_at, "
            "state, limit_hit) VALUES (?,?,?,?,?,?,?,?,?,?)",
            quota_rows,
        )

    if cleaned["conversations"]:
        conn.executemany(
            f"INSERT OR REPLACE INTO {CONVERSATIONS_TABLE} ("
            "peer_install_id, conversation_id, project, model, provider, agent_kind, account_id, "
            "subagent_type, agent_name, started_at, ended_at, tokens, cost_nano, turns, impact_score) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(origin, *r) for r in cleaned["conversations"]],
        )

    if cleaned["events"]:
        conn.executemany(
            f"INSERT OR REPLACE INTO {EVENTS_TABLE} ("
            "peer_install_id, event_id, occurred_at, kind, subject, data) VALUES (?,?,?,?,?,?)",
            [(origin, *r) for r in cleaned["events"]],
        )

    if cleaned["coverage"] is not None:
        conn.execute(
            f"INSERT OR REPLACE INTO {COVERAGE_TABLE} ("
            "peer_install_id, earliest_ts, latest_ts, minute_rows, unknown_cost_rows, "
            "tracked_sources, db_bytes, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (origin, *cleaned["coverage"], now_f),
        )

    if cleaned["mcp"]:
        conn.executemany(
            f"INSERT OR REPLACE INTO {MCP_TABLE} ("
            "peer_install_id, hour, server, tool, calls, errors, total_ms) VALUES (?,?,?,?,?,?,?)",
            [(origin, *r) for r in cleaned["mcp"]],
        )

    conn.execute(f"DELETE FROM {USAGE_5M_TABLE} WHERE peer_install_id = ? AND bucket_5m < ?", (origin, prune_cutoff))
    conn.execute(
        f"DELETE FROM {ACTIVITY_TABLE} WHERE peer_install_id = ? AND grain = 300 AND bucket_ts < ?",
        (origin, prune_cutoff),
    )
    conn.execute(
        f"DELETE FROM {QUOTA_TABLE} WHERE peer_install_id = ? AND grain = 300 AND bucket_ts < ?",
        (origin, prune_cutoff),
    )

    conv_meta: Dict[str, Tuple[str, str]] = cleaned["conv_meta"]
    if conv_meta:
        conn.executemany(
            f"UPDATE {USAGE_TABLE} SET account_id = ?, subagent_type = ? "
            "WHERE peer_install_id = ? AND conversation_id = ?",
            [(acct, stype, origin, cid) for cid, (acct, stype) in conv_meta.items()],
        )

    conn.execute(
        f"UPDATE {STATE_TABLE} SET v2_rev = ?, v2_epoch = NULL, v2_sig = NULL, v2_blob = NULL "
        "WHERE peer_install_id = ?",
        (0 if rev is None else int(rev), origin),
    )
    return True


def apply_v2_signed(
    conn: sqlite3.Connection,
    origin: str,
    payload: Any,
    rev: int,
    sig: str,
    epoch: int,
    *,
    now: Optional[float] = None,
) -> bool:
    state_row = conn.execute(
        f"SELECT v2_rev, v2_sig FROM {STATE_TABLE} WHERE peer_install_id = ?", (origin,)
    ).fetchone()
    if state_row is None or not relay_store.admit_epoch(conn, origin, epoch):
        return False
    if rev < relay_store.origin_rev(conn, origin, V2_FLOOR_KEY, 0):
        return False
    prev_rev, prev_sig = state_row[0], state_row[1]
    if not apply_v2(conn, origin, payload, rev=rev, now=now):
        return False
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    conn.execute(
        f"UPDATE {STATE_TABLE} SET v2_rev = ?, v2_epoch = ?, v2_sig = ?, v2_blob = ? WHERE peer_install_id = ?",
        (rev, epoch, sig, blob, origin),
    )
    relay_store.raise_origin_rev(conn, origin, V2_FLOOR_KEY, 0, rev)
    if prev_rev != rev or prev_sig != sig:
        relay_store._next_rev(conn)
    return True


def _conv_meta_touches_denied(
    conn: sqlite3.Connection, origin: str, conv_meta: Any, deny: FrozenSet[str]
) -> bool:
    if not deny or not isinstance(conv_meta, dict) or not conv_meta:
        return False
    rows = conn.execute(
        f"SELECT DISTINCT conversation_id, project FROM {USAGE_TABLE} WHERE peer_install_id = ?", (origin,)
    ).fetchall()
    return any(str(r[0]) in conv_meta and str(r[1]) in deny for r in rows)


def _unsigned_relay_v2(conn: sqlite3.Connection, origin: str, deny: FrozenSet[str]) -> Optional[Dict[str, Any]]:
    usage_5m = [
        list(r) for r in conn.execute(
            f"SELECT conversation_id, bucket_5m, provider, agent_kind, model, project, account_id, subagent_type, "
            "input, cache_write, cache_read, output, cost_nano, messages, priced, agent_name "
            f"FROM {USAGE_5M_TABLE} WHERE peer_install_id = ? ORDER BY bucket_5m, conversation_id, model, project",
            (origin,),
        )
        if r[5] not in deny
    ]
    activity = [
        list(r) for r in conn.execute(
            f"SELECT conversation_id, bucket_ts, grain, provider, agent_kind, model, project, "
            "observed_seconds, working_seconds, running_seconds, starts, completions, waiting_seconds, "
            "subagent_seconds, global_observed_seconds "
            f"FROM {ACTIVITY_TABLE} WHERE peer_install_id = ? ORDER BY grain, bucket_ts, conversation_id, project",
            (origin,),
        )
        if r[6] not in deny
    ]
    quota = [
        list(r) for r in conn.execute(
            f"SELECT bucket_ts, grain, provider, account_id, window, utilization, fetched_at, state, limit_hit "
            f"FROM {QUOTA_TABLE} WHERE peer_install_id = ? ORDER BY grain, bucket_ts, provider, account_id, window",
            (origin,),
        )
    ]
    conversations = [
        list(r) for r in conn.execute(
            f"SELECT conversation_id, project, model, provider, agent_kind, account_id, subagent_type, "
            "agent_name, started_at, ended_at, tokens, cost_nano, turns, impact_score "
            f"FROM {CONVERSATIONS_TABLE} WHERE peer_install_id = ? ORDER BY ended_at DESC, conversation_id",
            (origin,),
        )
        if r[1] not in deny
    ]
    events = [
        list(r) for r in conn.execute(
            f"SELECT event_id, occurred_at, kind, subject, data FROM {EVENTS_TABLE} "
            "WHERE peer_install_id = ? ORDER BY occurred_at DESC, event_id DESC",
            (origin,),
        )
    ]
    cov_row = conn.execute(
        f"SELECT earliest_ts, latest_ts, minute_rows, unknown_cost_rows, tracked_sources, db_bytes "
        f"FROM {COVERAGE_TABLE} WHERE peer_install_id = ?",
        (origin,),
    ).fetchone()
    coverage = None if cov_row is None else {
        "earliest_ts": cov_row[0], "latest_ts": cov_row[1], "minute_rows": cov_row[2],
        "unknown_cost_rows": cov_row[3], "tracked_sources": cov_row[4], "db_bytes": cov_row[5],
    }
    mcp = [
        list(r) for r in conn.execute(
            f"SELECT hour, server, tool, calls, errors, total_ms FROM {MCP_TABLE} "
            "WHERE peer_install_id = ? ORDER BY hour, server, tool",
            (origin,),
        )
    ]
    denied_convs: set[str] = set()
    if deny:
        denied_convs = {
            str(r[0]) for r in conn.execute(
                f"SELECT DISTINCT conversation_id, project FROM {USAGE_TABLE} WHERE peer_install_id = ?", (origin,)
            )
            if r[1] in deny
        }
    conv_meta: Dict[str, List[str]] = {}
    for cid, acct, stype in conn.execute(
        f"SELECT conversation_id, MAX(account_id), MAX(subagent_type) FROM {USAGE_TABLE} "
        "WHERE peer_install_id = ? GROUP BY conversation_id",
        (origin,),
    ):
        cid_s = str(cid)
        if cid_s in denied_convs:
            continue
        if acct != "unknown" or stype != "unknown":
            conv_meta[cid_s] = [str(acct), str(stype)]
    if not (usage_5m or activity or quota or conversations or events or coverage is not None or mcp or conv_meta):
        return None
    return {
        "v2": {
            "conv_meta": conv_meta,
            "usage_5m": usage_5m,
            "activity": activity,
            "quota": quota,
            "conversations": conversations,
            "events": events,
            "coverage": coverage,
            "mcp": mcp,
        }
    }


def relay_v2_for(
    conn: sqlite3.Connection,
    origin: str,
    deny: FrozenSet[str],
    signed_form: bool,
) -> Optional[Dict[str, Any]]:
    if not signed_form:
        return _unsigned_relay_v2(conn, origin, deny)
    row = conn.execute(
        f"SELECT v2_rev, v2_epoch, v2_sig, v2_blob FROM {STATE_TABLE} WHERE peer_install_id = ?",
        (origin,),
    ).fetchone()
    if row is None or row[0] is None or row[1] is None or not row[2] or not row[3]:
        return None
    try:
        payload = json.loads(row[3])
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if (deny and (v2_projects(payload) & deny)) or _conv_meta_touches_denied(conn, origin, payload.get("conv_meta"), deny):
        if "v2_denied" not in _noted:
            _noted.add("v2_denied")
            logger.warning("pack_rollup_relay_signed_v2_left_out")
        return None
    return {
        "v2": payload,
        "v2_rev": int(row[0]),
        "v2_epoch": int(row[1]),
        "v2_sig": {"signer": origin, "sig": str(row[2])},
    }

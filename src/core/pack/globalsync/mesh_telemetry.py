
from __future__ import annotations

import asyncio
import json
import math
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple

import structlog

from src.core import host_metrics
from src.core.computers import direction
from src.core.deepsearch import peer_air_gap
from src.core.federation import peer_ledger
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.pack.machines import capabilities, config_state, exchange
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.meshdata import gossip, telemetry_kind
from src.core.stats import agent_names, project_groups, rollup
from src.core.stats.project_groups import other_label
from src.core.stats.queries import _REAL_USAGE, _TOKEN_TOTAL
from src.core.stats_feed.model import Classes, trailing_rate
from src.models.provider_ledger import AccountUsage, UsageWindow

log = structlog.get_logger(__name__)

KIND = telemetry_kind.KIND
TTL_SECONDS = telemetry_kind.TTL_SECONDS
REFRESH_SECONDS = telemetry_kind.REFRESH_SECONDS
MAX_VALUE_BYTES = telemetry_kind.MAX_VALUE_BYTES

_LIVE_WINDOWS = (5, 15, 60)
_VALID_CRED_STATES: FrozenSet[str] = frozenset({
    "ok",
    "expired",
    "missing",
    "refused",
    "rate_limited",
    "error",
    "unknown",
})
_VALID_PROVIDERS: FrozenSet[str] = frozenset({"claude", "codex", "antigravity"})


def _clean_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("/", "-").replace("\\", "-")
    text = "".join(ch for ch in text if ch.isprintable()).strip()
    return text[:limit]


def _finite_float(value: Any, *, lo: float = 0.0, hi: float = telemetry_kind.MAX_RATE, digits: int = 3) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    fval = float(value)
    if not math.isfinite(fval) or fval < lo or fval > hi:
        return None
    return round(fval, digits)


def _strict_int(value: Any, *, lo: int = 0, hi: int = 10**16) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < lo or value > hi:
        return None
    return value


def _canonical_len(obj: Mapping[str, Any]) -> int:
    return len(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False))


def _sanitize_machine(raw: Mapping[str, Any], *, live_agents: Optional[int] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in ("cpu_percent", "memory_percent", "disk_percent"):
        val = _finite_float(raw.get(key), lo=0.0, hi=100.0, digits=1)
        if val is not None:
            out[key] = val
    for key in ("load_1", "load_5", "load_15"):
        val = _finite_float(raw.get(key), lo=0.0, hi=1e6, digits=2)
        if val is not None:
            out[key] = val
    for key in ("cpu_count", "memory_used_bytes", "memory_total_bytes", "disk_free_bytes", "disk_total_bytes", "uptime_seconds", "live_agents"):
        val = _strict_int(raw.get(key), lo=0, hi=10**16)
        if val is not None:
            out[key] = val
    if "live_agents" not in out and live_agents is not None and live_agents >= 0:
        out["live_agents"] = int(live_agents)
    return out


def _read_live_agents(app_db: Any) -> Optional[int]:
    if app_db is None:
        return None
    try:
        row = app_db.execute(
            "SELECT COUNT(*) FROM sessions WHERE host_key = ? AND lifecycle = 'running'",
            (LOCAL_HOST_KEY,),
        ).fetchone()
        return int(row[0]) if row is not None else 0
    except (sqlite3.Error, AttributeError, TypeError):
        return None


def _read_local_machine(app_db: Any, state_dir: Optional[str] = None) -> Dict[str, Any]:
    from src.config import settings

    target_dir = state_dir or str(settings.get_state_dir())
    mem = host_metrics.collect_memory()
    disk = host_metrics.collect_disk(target_dir)
    load = host_metrics.collect_load()
    host = host_metrics.collect_host()
    raw: Dict[str, Any] = {
        "cpu_count": os.cpu_count() or None,
        "memory_percent": mem.get("used_percent") if mem.get("available") else None,
        "memory_used_bytes": mem.get("used_bytes") if mem.get("available") else None,
        "memory_total_bytes": mem.get("total_bytes") if mem.get("available") else None,
        "disk_percent": disk.get("used_percent") if disk.get("available") else None,
        "disk_free_bytes": disk.get("free_bytes") if disk.get("available") else None,
        "disk_total_bytes": disk.get("total_bytes") if disk.get("available") else None,
        "load_1": load.get("load_1") if load.get("available") else None,
        "load_5": load.get("load_5") if load.get("available") else None,
        "load_15": load.get("load_15") if load.get("available") else None,
        "uptime_seconds": host.get("uptime_seconds"),
    }
    return _sanitize_machine(raw, live_agents=_read_live_agents(app_db))


def _sanitize_feed_rate(raw: Any) -> Optional[Dict[str, float]]:
    if not isinstance(raw, Mapping):
        return None
    out: Dict[str, float] = {}
    for key in ("span_seconds", "fresh", "cache_write", "cache_read", "out"):
        hi = 1e6 if key == "span_seconds" else telemetry_kind.MAX_RATE
        val = _finite_float(raw.get(key), lo=0.0, hi=hi, digits=1)
        if val is None:
            return None
        out[key] = val
    return out


def _sanitize_feed_buckets(raw: Any) -> List[List[int]]:
    if not isinstance(raw, (list, tuple)):
        return []
    clean: List[List[int]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 5:
            continue
        ints = [_strict_int(x, lo=0, hi=telemetry_kind.MAX_COUNT) for x in item]
        if any(x is None for x in ints):
            continue
        clean.append([int(x) for x in ints if x is not None])
    clean.sort(key=lambda b: b[0])
    return clean[-telemetry_kind.MAX_FEED_BUCKETS :]


def _format_reset_stamp(value: Any) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        cleaned = _clean_text(value, 64)
        return cleaned or None
    return _finite_float(value, lo=0.0, hi=telemetry_kind.MAX_EPOCH, digits=1)


def _sanitize_ledger_entry(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, AccountUsage):
        if raw.relayed:
            return None
        five_h = next((w for w in raw.windows if w.kind in ("five_hour", "primary")), None)
        seven_d = next((w for w in raw.windows if w.kind in ("seven_day", "secondary")), None)
        acct_key = peer_ledger.identity_key(raw.provider, raw.identity)
        item: Dict[str, Any] = {
            "provider": raw.provider,
            "id": _clean_text(raw.id, 64),
            "name": _clean_text(raw.name, 96),
            "credential_state": raw.credential_state if raw.credential_state in _VALID_CRED_STATES else "unknown",
        }
        if acct_key:
            item["account_key"] = _clean_text(acct_key, telemetry_kind.MAX_STR)
        if raw.plan:
            item["plan"] = _clean_text(raw.plan, 64)
        if five_h is not None:
            pct = _finite_float(five_h.used_pct, lo=0.0, hi=100.0, digits=1)
            if pct is not None:
                item["five_hour_pct"] = pct
            res = _format_reset_stamp(five_h.resets_at)
            if res is not None:
                item["five_hour_resets_at"] = res
        if seven_d is not None:
            pct = _finite_float(seven_d.used_pct, lo=0.0, hi=100.0, digits=1)
            if pct is not None:
                item["seven_day_pct"] = pct
            res = _format_reset_stamp(seven_d.resets_at)
            if res is not None:
                item["seven_day_resets_at"] = res
        return item

    if not isinstance(raw, Mapping):
        return None
    provider = raw.get("provider")
    if provider not in _VALID_PROVIDERS:
        return None
    item = {"provider": provider}
    for key, limit in (("account_key", telemetry_kind.MAX_STR), ("id", 64), ("name", 96), ("plan", 64)):
        if raw.get(key) is not None:
            cleaned = _clean_text(raw.get(key), limit)
            if cleaned:
                item[key] = cleaned
    for pct_key in ("five_hour_pct", "seven_day_pct"):
        pct = _finite_float(raw.get(pct_key), lo=0.0, hi=100.0, digits=1)
        if pct is not None:
            item[pct_key] = pct
    for reset_key in ("five_hour_resets_at", "seven_day_resets_at"):
        res = _format_reset_stamp(raw.get(reset_key))
        if res is not None:
            item[reset_key] = res
    cred = raw.get("credential_state")
    if isinstance(cred, str) and cred in _VALID_CRED_STATES:
        item["credential_state"] = cred
    spend = _finite_float(raw.get("spend_usd"), lo=0.0, hi=1e9, digits=4)
    if spend is not None:
        item["spend_usd"] = spend
    return item


def _collect_stats_sections(
    stats_store: Any,
    now_ts: float,
    feed_snapshot: Optional[Mapping[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    vitals: Dict[str, Any] = {}
    hot: List[Dict[str, Any]] = []
    agents: List[Dict[str, Any]] = []

    allow: Optional[FrozenSet[str]] = None
    if stats_store is not None:
        try:
            allow = rollup.allowed_projects(stats_store)
        except peer_air_gap.AirGapUnreadable:
            log.warning("mesh_telemetry_air_gap_unreadable")
            return vitals, hot, agents

    if stats_store is not None:
        current = int(now_ts // 60) * 60
        since = current - (max(_LIVE_WINDOWS) - 1) * 60
        try:
            with stats_store.connect_read() as db:
                rows = db.execute(
                    "SELECT minute_ts,provider,conversation_id,project,model,"
                    f"({_TOKEN_TOTAL}) AS tokens,input_tokens,cache_write_tokens,cache_read_tokens,output_tokens,"
                    f"estimated_cost_nano_usd AS cost FROM minute_usage WHERE minute_ts>=? AND minute_ts<=? AND {_REAL_USAGE}",
                    (since, current),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            log.warning("mesh_telemetry_stats_read_failed", error=type(exc).__name__)
            rows = []

        if allow is not None:
            rows = [r for r in rows if r["project"] in allow]

        for w in _LIVE_WINDOWS:
            lo = current - (w - 1) * 60
            sel = [r for r in rows if r["minute_ts"] >= lo]
            if sel:
                vitals[f"tpm_{w}m"] = round(sum(int(r["tokens"]) for r in sel) / w, 3)
            costs = [int(r["cost"]) for r in sel if r["cost"] is not None]
            if costs:
                vitals[f"usd_hr_{w}m"] = round(sum(costs) / 1e9 / w * 60, 6)

        lo15 = current - 14 * 60
        recent = [r for r in rows if r["minute_ts"] >= lo15]
        denom = sum(int(r["input_tokens"]) + int(r["cache_write_tokens"]) + int(r["cache_read_tokens"]) for r in recent)
        if denom > 0:
            vitals["cache_read_15m"] = sum(int(r["cache_read_tokens"]) for r in recent)
            vitals["cache_denom_15m"] = denom

        models: Dict[str, int] = {}
        convs: Dict[Tuple[str, str], Dict[str, Any]] = {}
        minute_buckets: Dict[int, Classes] = {}
        for r in recent:
            model_name = _clean_text(r["model"], 96)
            tok = int(r["tokens"])
            if model_name:
                models[model_name] = models.get(model_name, 0) + tok
            key = (str(r["provider"]), str(r["conversation_id"]))
            entry = convs.setdefault(key, {"tokens": 0, "cost": None, "project": r["project"], "models": {}})
            entry["tokens"] += tok
            if r["cost"] is not None:
                entry["cost"] = (entry["cost"] or 0) + int(r["cost"])
            if model_name:
                entry["models"][model_name] = entry["models"].get(model_name, 0) + tok
            m_ts = int(r["minute_ts"])
            minute_buckets[m_ts] = minute_buckets.get(m_ts, Classes()).plus(
                Classes(int(r["input_tokens"]), int(r["cache_write_tokens"]), int(r["cache_read_tokens"]), int(r["output_tokens"]))
            )

        if models:
            ranked_models = sorted(models.items(), key=lambda kv: (-kv[1], kv[0]))[: telemetry_kind.MAX_ACTIVE_MODELS]
            vitals["active_models_15m"] = [m for m, _ in ranked_models]
            vitals["model_tokens_15m"] = {m: t for m, t in ranked_models}

        top = sorted(convs.items(), key=lambda kv: (-kv[1]["tokens"], kv[0]))[: telemetry_kind.MAX_HOT]
        groups = project_groups.groups_for(stats_store) if top else None
        for (provider, conv_id), c in top:
            clean_conv = _clean_text(conv_id, telemetry_kind.MAX_STR)
            clean_prov = _clean_text(provider, 32)
            if not clean_conv or not clean_prov:
                continue
            proj_label = groups.conversation_label(c["project"]) if groups else other_label(1)
            top_model = max(c["models"], key=lambda m: (c["models"][m], m)) if c["models"] else ""
            hot_entry: Dict[str, Any] = {
                "conversation_id": clean_conv,
                "provider": clean_prov,
                "project": _clean_text(proj_label, telemetry_kind.MAX_STR),
                "model": _clean_text(top_model, 96),
                "tokens": int(c["tokens"]),
            }
            if c["cost"] is not None:
                hot_entry["cost_nano"] = int(c["cost"])
            hot.append(hot_entry)

        lo5 = current - 4 * 60
        agent_totals: Dict[str, int] = {}
        for r in rows:
            if int(r["minute_ts"]) >= lo5:
                root = agent_names.root_of(str(r["conversation_id"]))
                agent_totals[root] = agent_totals.get(root, 0) + int(r["tokens"])
        if agent_totals:
            names = agent_names.names_for(stats_store)
            ranked_agents = sorted(
                ((cid, tok) for cid, tok in agent_totals.items() if tok > 0),
                key=lambda kv: (-kv[1], kv[0]),
            )[: telemetry_kind.MAX_AGENTS]
            for cid, tok in ranked_agents:
                clean_cid = _clean_text(cid, telemetry_kind.MAX_STR)
                if not clean_cid:
                    continue
                agents.append({
                    "conversation_id": clean_cid,
                    "name": _clean_text(names.get(cid, agent_names.UNNAMED), 96),
                    "tokens": int(tok),
                    "tokens_per_minute": round(tok / 5.0, 2),
                })

        if feed_snapshot is None and minute_buckets:
            vitals["feed_buckets_1m"] = [
                [ts, b.fresh, b.cache_write, b.cache_read, b.out]
                for ts, b in sorted(minute_buckets.items())[-telemetry_kind.MAX_FEED_BUCKETS :]
                if any(b)
            ]
            rate = _sanitize_feed_rate(trailing_rate(minute_buckets, now_ts))
            if rate is not None:
                vitals["feed_rate"] = rate

    if feed_snapshot is not None:
        raw_rate = feed_snapshot.get("feed_rate") if "feed_rate" in feed_snapshot else feed_snapshot.get("rate")
        rate = _sanitize_feed_rate(raw_rate)
        if rate is not None:
            vitals["feed_rate"] = rate
        raw_buckets = feed_snapshot.get("feed_buckets_1m") if "feed_buckets_1m" in feed_snapshot else feed_snapshot.get("buckets_1m")
        buckets = _sanitize_feed_buckets(raw_buckets)
        if buckets:
            vitals["feed_buckets_1m"] = buckets

    return vitals, hot, agents


def _trim_to_budget(payload: Dict[str, Any]) -> Dict[str, Any]:
    if _canonical_len(payload) <= MAX_VALUE_BYTES:
        return payload
    vitals = payload.get("vitals_15m")
    if isinstance(vitals, dict) and isinstance(vitals.get("feed_buckets_1m"), list):
        buckets = vitals["feed_buckets_1m"]
        while buckets and _canonical_len(payload) > MAX_VALUE_BYTES:
            buckets.pop(0)
        if not buckets:
            vitals.pop("feed_buckets_1m", None)
    for section in ("agents_5m", "hot_15m", "ledger"):
        items = payload.get(section)
        if isinstance(items, list):
            while items and _canonical_len(payload) > MAX_VALUE_BYTES:
                items.pop()
            if not items:
                payload.pop(section, None)
    if isinstance(vitals, dict) and _canonical_len(payload) > MAX_VALUE_BYTES:
        vitals.pop("model_tokens_15m", None)
        models = vitals.get("active_models_15m")
        if isinstance(models, list):
            while models and _canonical_len(payload) > MAX_VALUE_BYTES:
                models.pop()
            if not models:
                vitals.pop("active_models_15m", None)
    if _canonical_len(payload) > MAX_VALUE_BYTES:
        payload.pop("vitals_15m", None)
    if _canonical_len(payload) > MAX_VALUE_BYTES:
        payload.pop("machine", None)
    return payload


def collect(
    app_db: Any,
    stats_store: Any,
    *,
    self_id: str,
    label: str,
    app_version: str = "",
    machine: Optional[Dict[str, Any]] = None,
    ledger_accounts: Optional[List[Any]] = None,
    feed_snapshot: Optional[Dict[str, Any]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    _ = self_id
    now_ts = round(time.time() if now is None else float(now), 3)
    payload: Dict[str, Any] = {
        "ts": now_ts,
        "label": _clean_text(label, telemetry_kind.MAX_LABEL),
        "app_version": _clean_text(app_version, telemetry_kind.MAX_VERSION),
    }

    vitals, hot, agents = _collect_stats_sections(stats_store, now_ts, feed_snapshot)
    if vitals:
        payload["vitals_15m"] = vitals
    if hot:
        payload["hot_15m"] = hot
    if agents:
        payload["agents_5m"] = agents

    if machine is not None:
        clean_machine = _sanitize_machine(machine)
    else:
        clean_machine = _read_local_machine(app_db)
    if clean_machine:
        payload["machine"] = clean_machine

    if ledger_accounts is not None:
        clean_ledger: List[Dict[str, Any]] = []
        for raw_acct in ledger_accounts:
            sanitized = _sanitize_ledger_entry(raw_acct)
            if sanitized is not None:
                clean_ledger.append(sanitized)
            if len(clean_ledger) >= telemetry_kind.MAX_LEDGER:
                break
        if clean_ledger:
            payload["ledger"] = clean_ledger

    return _trim_to_budget(payload)


def publish_now(
    store: Any,
    lst: Any,
    signing: Any,
    payload: Dict[str, Any],
    *,
    now_ms: Optional[int] = None,
    gen: Optional[int] = None,
) -> bool:
    _ = now_ms
    if not isinstance(lst, RosterV2) or not telemetry_kind.valid(payload):
        return False
    if not telemetry_kind.approved(lst, signing.install_id):
        return False
    return bool(store.put_own(KIND, signing.install_id, payload, signing, force=True, lst=lst, gen=gen))


def fresh_peers(
    store: Any,
    lst: Any,
    self_id: str,
    *,
    now: Optional[float] = None,
    ttl_seconds: float = TTL_SECONDS,
) -> Dict[str, Dict[str, Any]]:
    if store is None or not isinstance(lst, RosterV2):
        return {}
    now_ts = time.time() if now is None else float(now)
    rows = store.kind_rows(lst, KIND)
    withheld = store.withholding(lst, self_id)
    out: Dict[str, Dict[str, Any]] = {}
    for key, (val, stamp) in rows.items():
        origin = stamp.iid
        if origin != key or origin == self_id:
            continue
        if origin in withheld or direction.contained(origin) or direction.listed_one_way(lst, origin):
            continue
        if not isinstance(val, dict):
            continue
        ts = val.get("ts")
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not math.isfinite(ts):
            continue
        if abs(now_ts - float(ts)) > ttl_seconds:
            continue
        out[origin] = val
    return out


def active_peers(*, now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    if not capabilities.mesh_on():
        return {}
    active = gossip.ACTIVE
    if active is None:
        return {}
    try:
        if not config_state.default().restrictions().may_receive_pack_ui:
            return {}
        runtime = exchange.RUNTIME
        lst = runtime.held_list() if runtime is not None else active.held_list()
        if not isinstance(lst, RosterV2):
            return {}
        return fresh_peers(active.store, lst, active.store.own_iid, now=now)
    except (sqlite3.Error, OSError, ValueError) as exc:
        log.warning("mesh_telemetry_active_peers_failed", error=type(exc).__name__)
        return {}


def _parse_reset_dt(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw):
        return datetime.fromtimestamp(float(raw), timezone.utc)
    if isinstance(raw, str):
        text = raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def ledger_rows_from_telemetry(
    peer_telemetry: Mapping[str, Mapping[str, Any]],
    existing_keys: Mapping[str, Optional[str]],
    existing_rows: List[AccountUsage],
) -> Tuple[List[AccountUsage], Dict[str, Optional[str]]]:
    seen_keys: Set[Tuple[str, str]] = set()
    for row in existing_rows:
        ekey = existing_keys.get(row.id)
        if ekey:
            seen_keys.add((row.provider, ekey))
        seen_keys.add((row.provider, row.id))

    mesh_rows: List[AccountUsage] = []
    extra_keys: Dict[str, Optional[str]] = {}

    for origin_iid, tel in sorted(peer_telemetry.items()):
        if not isinstance(tel, Mapping):
            continue
        raw_ledger = tel.get("ledger")
        if not isinstance(raw_ledger, list):
            continue
        tel_ts = tel.get("ts")
        synced_dt = (
            datetime.fromtimestamp(float(tel_ts), timezone.utc)
            if isinstance(tel_ts, (int, float)) and not isinstance(tel_ts, bool) and math.isfinite(tel_ts)
            else None
        )
        for idx, acct in enumerate(raw_ledger):
            if not isinstance(acct, Mapping):
                continue
            provider = acct.get("provider")
            if provider not in _VALID_PROVIDERS:
                continue
            acct_key = acct.get("account_key")
            raw_id = acct.get("id")
            dedupe_key = str(acct_key) if acct_key else (str(raw_id) if raw_id else None)
            if dedupe_key and (provider, dedupe_key) in seen_keys:
                continue
            if raw_id and (provider, str(raw_id)) in seen_keys:
                continue
            if dedupe_key:
                seen_keys.add((provider, dedupe_key))
            if raw_id:
                seen_keys.add((provider, str(raw_id)))

            windows: List[UsageWindow] = []
            if acct.get("five_hour_pct") is not None:
                windows.append(
                    UsageWindow(
                        kind="five_hour" if provider == "claude" else "primary",
                        label="5h",
                        used_pct=float(acct["five_hour_pct"]),
                        window_seconds=18000,
                        resets_at=_parse_reset_dt(acct.get("five_hour_resets_at")),
                    )
                )
            if acct.get("seven_day_pct") is not None:
                windows.append(
                    UsageWindow(
                        kind="seven_day" if provider == "claude" else "secondary",
                        label="7d",
                        used_pct=float(acct["seven_day_pct"]),
                        window_seconds=604800,
                        resets_at=_parse_reset_dt(acct.get("seven_day_resets_at")),
                    )
                )

            cred = acct.get("credential_state")
            cred_state = cred if isinstance(cred, str) and cred in _VALID_CRED_STATES else "ok"
            row_id = f"mesh:{origin_iid[:12]}:{raw_id or dedupe_key or idx}"
            row_name = str(acct.get("name") or raw_id or provider)
            mesh_rows.append(
                AccountUsage(
                    id=row_id,
                    name=row_name,
                    provider=provider,
                    plan=str(acct["plan"]) if acct.get("plan") is not None else None,
                    credential_state=cred_state,  # type: ignore[arg-type]
                    fetched_at=synced_dt,
                    synced_at=synced_dt,
                    windows=windows,
                    relayed=True,
                )
            )
            extra_keys[row_id] = dedupe_key

    return mesh_rows, extra_keys


def attach(
    app_state: Any,
    open_db: Callable[[], Any],
    *,
    label: Callable[[], str],
    app_version: str,
    state_dir: str,
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
) -> Callable[[Any, Any], Any]:
    state: Dict[str, float] = {"last_mono": float("-inf")}

    def _collect_and_publish(service: Any, lst: Any, gen: Optional[int]) -> bool:
        from src.core.provider_ledger import poller

        stats_store = getattr(app_state, "stats_store", None)
        watch = getattr(app_state, "machine_stats_watch", None)
        machine_reading: Optional[Dict[str, Any]] = None
        if watch is not None:
            try:
                machine_reading = dict(watch.sampler.read())
            except (OSError, ValueError, RuntimeError):
                machine_reading = None
        ledger_accounts = [acct for acct in poller.snapshot().accounts if not acct.relayed]
        with closing(open_db()) as conn:
            live_agents = _read_live_agents(conn)
            if machine_reading is not None:
                machine_reading = _sanitize_machine(machine_reading, live_agents=live_agents)
            else:
                machine_reading = _read_local_machine(conn, state_dir=state_dir)
            payload = collect(
                conn,
                stats_store,
                self_id=service.store.own_iid,
                label=label(),
                app_version=app_version,
                machine=machine_reading,
                ledger_accounts=ledger_accounts,
                now=wall(),
            )
        return publish_now(service.store, lst, service.signing, payload, gen=gen)

    async def step(service: Any, lst: Any) -> None:
        if not telemetry_kind.approved(lst, service.store.own_iid):
            return
        if not config_state.default().restrictions().may_receive_pack_ui:
            return
        now_mono = clock()
        if now_mono - state["last_mono"] < REFRESH_SECONDS:
            return
        wrote = await asyncio.to_thread(_collect_and_publish, service, lst, service.pass_gen)
        if wrote:
            state["last_mono"] = now_mono

    return step

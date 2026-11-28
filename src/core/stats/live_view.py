from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.core.session_token_usage.model_table import readable_model_name
from src.core.stats import agent_names, project_groups
from src.core.stats.project_groups import other_label
from src.core.stats.queries import _REAL_USAGE, _TOKEN_TOTAL
from src.core.stats.store_port import StatsStoreLike

_LIVE_WINDOWS = (5, 15, 60)
_AGENTS_LIMIT = 50
_live_lock = threading.Lock()
_live_inflight: dict[str, threading.Lock] = {}
_live_memo: dict[str, tuple[int, int, str, str, dict]] = {}


def _peer_digest(peer_telemetry: Optional[Dict[str, Dict[str, Any]]]) -> str:
    if not peer_telemetry:
        return ""
    raw = json.dumps(peer_telemetry, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _resolve_peer_telemetry(
    peer_telemetry: Optional[Dict[str, Dict[str, Any]]],
    scope: str,
    now: float,
) -> Optional[Dict[str, Dict[str, Any]]]:
    if scope != "pack":
        return None
    if peer_telemetry is not None:
        return peer_telemetry
    from src.core.pack.globalsync import mesh_telemetry

    peers = mesh_telemetry.active_peers(now=now)
    return peers or None


def live_v2_cached(
    store: StatsStoreLike,
    now: float | None = None,
    *,
    peer_telemetry: Optional[Dict[str, Dict[str, Any]]] = None,
    scope: str = "pack",
) -> dict:
    now = time.time() if now is None else now
    resolved_peers = _resolve_peer_telemetry(peer_telemetry, scope, now)
    digest = _peer_digest(resolved_peers)
    path = str(getattr(store, "db_path", None) or id(store))
    revision, minute = store.revision(), int(now // 60)
    cache_key = (revision, minute, scope, digest)
    with _live_lock:
        held = _live_memo.get(path)
        if held is not None and held[:4] == cache_key:
            return held[4]
        key_lock = _live_inflight.setdefault(path, threading.Lock())
    with key_lock:
        with _live_lock:
            held = _live_memo.get(path)
        if held is not None and held[:4] == cache_key:
            return held[4]
        answer = (
            live_v2(store, now, peer_telemetry=resolved_peers, scope=scope)
            if resolved_peers or scope != "pack"
            else live_v2(store, now)
        )
        with _live_lock:
            _live_memo[path] = (revision, minute, scope, digest, answer)
        return answer


def _agents_5m(rows: list, current: int, names: dict[str, str]) -> list[dict]:
    lo = current - 4 * 60
    totals: dict[str, int] = {}
    for r in rows:
        if r["minute_ts"] >= lo:
            root = agent_names.root_of(r["conversation_id"])
            totals[root] = totals.get(root, 0) + r["tokens"]
    ranked = sorted(((conv, tokens) for conv, tokens in totals.items() if tokens > 0), key=lambda kv: (-kv[1], kv[0]))
    return [{"conversation_id": conv, "name": names.get(conv, agent_names.UNNAMED), "tokens": tokens,
             "tokens_per_minute": tokens / 5} for conv, tokens in ranked[:_AGENTS_LIMIT]]


def _merge_pack_telemetry(
    local_result: Dict[str, Any],
    *,
    local_cache_read: int,
    local_cache_denom: int,
    local_models: Dict[str, int],
    peer_telemetry: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    burn: Dict[str, Dict[str, Any]] = {
        key: dict(val) for key, val in local_result["burn"].items()
    }
    total_cr = float(local_cache_read)
    total_denom = float(local_cache_denom)

    convs: Dict[Tuple[str, str], Dict[str, Any]] = {
        (item["provider"], item["conversation_id"]): dict(item)
        for item in local_result["top_conversations_15m"]
    }
    agents: Dict[str, Dict[str, Any]] = {
        item["conversation_id"]: dict(item)
        for item in local_result["agents_5m"]
    }
    models: Dict[str, int] = dict(local_models)

    for tel in peer_telemetry.values():
        if not isinstance(tel, dict):
            continue
        vitals = tel.get("vitals_15m")
        if isinstance(vitals, dict):
            for w in _LIVE_WINDOWS:
                wk = f"{w}m"
                p_tpm = vitals.get(f"tpm_{wk}")
                if isinstance(p_tpm, (int, float)) and not isinstance(p_tpm, bool):
                    cur = burn[wk]["tokens_per_minute"]
                    burn[wk]["tokens_per_minute"] = (cur or 0.0) + float(p_tpm)
                p_usd = vitals.get(f"usd_hr_{wk}")
                if isinstance(p_usd, (int, float)) and not isinstance(p_usd, bool):
                    cur_usd = burn[wk]["estimated_usd_per_hour"]
                    burn[wk]["estimated_usd_per_hour"] = (cur_usd or 0.0) + float(p_usd)

            p_denom = vitals.get("cache_denom_15m")
            p_cr = vitals.get("cache_read_15m")
            if isinstance(p_denom, (int, float)) and not isinstance(p_denom, bool) and p_denom > 0:
                total_denom += float(p_denom)
                if isinstance(p_cr, (int, float)) and not isinstance(p_cr, bool) and p_cr >= 0:
                    total_cr += float(p_cr)

            mt = vitals.get("model_tokens_15m")
            has_mt = isinstance(mt, dict) and bool(mt)
            if has_mt:
                for m_name, m_tok in mt.items():
                    if isinstance(m_name, str) and isinstance(m_tok, int) and not isinstance(m_tok, bool):
                        models[m_name] = models.get(m_name, 0) + m_tok
            for m_name in vitals.get("active_models_15m") or []:
                if isinstance(m_name, str) and m_name:
                    models.setdefault(m_name, 0)

        for item in tel.get("hot_15m") or []:
            if not isinstance(item, dict):
                continue
            cid = item.get("conversation_id")
            prov = item.get("provider")
            if not isinstance(cid, str) or not cid or not isinstance(prov, str) or not prov:
                continue
            tok = int(item.get("tokens") or 0)
            model = str(item.get("model") or "")
            cost_nano = item.get("cost_nano")
            candidate = {
                "conversation_id": cid,
                "provider": prov,
                "project": item.get("project") or other_label(1),
                "model": model,
                "model_label": readable_model_name(model) or None,
                "tokens": tok,
                "estimated_cost_usd": cost_nano / 1e9 if isinstance(cost_nano, (int, float)) else None,
            }
            key = (prov, cid)
            if key not in convs or tok > int(convs[key].get("tokens") or 0):
                convs[key] = candidate
            if model and not (isinstance(vitals, dict) and isinstance(vitals.get("model_tokens_15m"), dict)):
                models[model] = models.get(model, 0) + tok

        for item in tel.get("agents_5m") or []:
            if not isinstance(item, dict):
                continue
            cid = item.get("conversation_id")
            if not isinstance(cid, str) or not cid:
                continue
            tok = int(item.get("tokens") or 0)
            tpm = float(item.get("tokens_per_minute", tok / 5.0))
            if cid not in agents or tok > int(agents[cid].get("tokens") or 0):
                agents[cid] = {
                    "conversation_id": cid,
                    "name": str(item.get("name") or agent_names.UNNAMED),
                    "tokens": tok,
                    "tokens_per_minute": tpm,
                }

    top_convs: List[Dict[str, Any]] = sorted(
        convs.values(),
        key=lambda c: (-int(c["tokens"]), str(c["provider"]), str(c["conversation_id"])),
    )[:5]
    top_agents: List[Dict[str, Any]] = sorted(
        agents.values(),
        key=lambda a: (-int(a["tokens"]), str(a["conversation_id"])),
    )[:_AGENTS_LIMIT]
    active_models = [m for m, _ in sorted(models.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {
        "burn": burn,
        "cache_hit_ratio_15m": total_cr / total_denom if total_denom > 0 else None,
        "top_conversations_15m": top_convs,
        "agents_5m": top_agents,
        "active_models_15m": active_models,
    }


def live_v2(
    store: StatsStoreLike,
    now: float | None = None,
    *,
    peer_telemetry: Optional[Dict[str, Dict[str, Any]]] = None,
    scope: str = "pack",
) -> dict:
    now = time.time() if now is None else now
    current = int(now // 60) * 60
    since = current - (max(_LIVE_WINDOWS) - 1) * 60
    with store.connect_read() as db:
        rows = db.execute(
            "SELECT minute_ts,provider,conversation_id,project,model,"
            f"({_TOKEN_TOTAL}) AS tokens,input_tokens,cache_write_tokens,cache_read_tokens,"
            f"estimated_cost_nano_usd AS cost FROM minute_usage WHERE minute_ts>=? AND minute_ts<=? AND {_REAL_USAGE}",
            (since, current)).fetchall()
    burn = {}
    for w in _LIVE_WINDOWS:
        lo = current - (w - 1) * 60
        sel = [r for r in rows if r["minute_ts"] >= lo]
        costs = [r["cost"] for r in sel if r["cost"] is not None]
        burn[f"{w}m"] = {
            "window_minutes": w,
            "tokens_per_minute": sum(r["tokens"] for r in sel) / w if sel else None,
            "estimated_usd_per_hour": sum(costs) / 1e9 / w * 60 if costs else None,
        }
    lo15 = current - 14 * 60
    recent = [r for r in rows if r["minute_ts"] >= lo15]
    cache_read = sum(r["cache_read_tokens"] for r in recent)
    denom = sum(r["input_tokens"] + r["cache_write_tokens"] + r["cache_read_tokens"] for r in recent)
    ratio = cache_read / denom if denom else None
    convs: dict[tuple, dict] = {}
    for r in recent:
        c = convs.setdefault((r["provider"], r["conversation_id"]),
                             {"tokens": 0, "cost": None, "project": r["project"], "models": {}})
        c["tokens"] += r["tokens"]
        if r["cost"] is not None:
            c["cost"] = (c["cost"] or 0) + r["cost"]
        c["models"][r["model"]] = c["models"].get(r["model"], 0) + r["tokens"]
    top = sorted(convs.items(), key=lambda kv: (-kv[1]["tokens"], kv[0]))[:5]
    groups = project_groups.groups_for(store) if top else None
    models: dict[str, int] = {}
    for r in recent:
        models[r["model"]] = models.get(r["model"], 0) + r["tokens"]
    local_result = {
        "burn": burn,
        "cache_hit_ratio_15m": ratio,
        "top_conversations_15m": [{
            "conversation_id": conv, "provider": provider,
            "project": groups.conversation_label(c["project"]) if groups else other_label(1),
            "model": (model := max(c["models"], key=lambda m: (c["models"][m], m))),
            "model_label": readable_model_name(model) or None,
            "tokens": c["tokens"],
            "estimated_cost_usd": c["cost"] / 1e9 if c["cost"] is not None else None,
        } for (provider, conv), c in top],
        "agents_5m": _agents_5m(rows, current, agent_names.names_for(store)),
        "active_models_15m": [m for m, _ in sorted(models.items(), key=lambda kv: (-kv[1], kv[0]))] if models else [],
    }
    if scope != "pack" or not peer_telemetry:
        return local_result
    return _merge_pack_telemetry(
        local_result,
        local_cache_read=cache_read,
        local_cache_denom=denom,
        local_models=models,
        peer_telemetry=peer_telemetry,
    )

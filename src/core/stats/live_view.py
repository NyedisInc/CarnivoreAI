from __future__ import annotations

import threading
import time

from src.core.session_token_usage.model_table import readable_model_name
from src.core.stats import agent_names, project_groups
from src.core.stats.project_groups import other_label
from src.core.stats.queries import _REAL_USAGE, _TOKEN_TOTAL

_LIVE_WINDOWS = (5, 15, 60)
_AGENTS_LIMIT = 50
_live_lock = threading.Lock()
_live_memo: dict[str, tuple[int, int, dict]] = {}


def live_v2_cached(store, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    path, revision, minute = str(getattr(store, "db_path", None) or id(store)), store.revision(), int(now // 60)
    with _live_lock:
        held = _live_memo.get(path)
    if held is not None and held[:2] == (revision, minute):
        return held[2]
    answer = live_v2(store, now)
    with _live_lock:
        _live_memo[path] = (revision, minute, answer)
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


def live_v2(store, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    current = int(now // 60) * 60
    since = current - (max(_LIVE_WINDOWS) - 1) * 60
    db = store.connect(readonly=True)
    try:
        rows = db.execute(
            "SELECT minute_ts,provider,conversation_id,project,model,"
            f"({_TOKEN_TOTAL}) AS tokens,input_tokens,cache_write_tokens,cache_read_tokens,"
            f"estimated_cost_nano_usd AS cost FROM minute_usage WHERE minute_ts>=? AND minute_ts<=? AND {_REAL_USAGE}",
            (since, current)).fetchall()
    finally:
        db.close()
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
    denom = sum(r["input_tokens"] + r["cache_write_tokens"] + r["cache_read_tokens"] for r in recent)
    ratio = sum(r["cache_read_tokens"] for r in recent) / denom if denom else None
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
    return {
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

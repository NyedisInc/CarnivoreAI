
from __future__ import annotations

from typing import Any, Dict

from src.core.pack.jobs import precheck_learn
from src.core.pack.jobs.store import JobStore
from src.core.pack.placement.workload import HEAVY_KINDS

P3_WINDOW_DAYS = 7
P3_OVER = 0.30
P3_MIN_SPAWNS = 20
LOAD_HOURS = 24
KEEP_DAYS = 30
DAY = 86400.0


def _share(part: float, whole: float) -> Any:
    return round(part / whole, 3) if whole > 0 else None


def p3(store: JobStore, *, now: float) -> Dict[str, Any]:
    cutoff = now - P3_WINDOW_DAYS * DAY
    counts = {"delegated": 0, "miss": 0, "local_ok": 0}
    for _uid, _minutes, outcome in store.episodes_since(cutoff):
        counts[outcome] = counts.get(outcome, 0) + 1
    calls = sum(1 for kind in store.request_kinds_since(cutoff, store.marked_projects()) if kind in HEAVY_KINDS)
    share = _share(counts["miss"], counts["miss"] + calls)
    first = store.first_metric_at()
    enough = first is not None and now - first >= P3_WINDOW_DAYS * DAY and sum(counts.values()) + calls >= P3_MIN_SPAWNS
    return {"window_days": P3_WINDOW_DAYS, "misses": counts["miss"], "local_ok": counts["local_ok"], "delegated": counts["delegated"],
            "delegate_calls": calls, "share": share, "threshold": P3_OVER, "over": bool(enough and share is not None and share > P3_OVER),
            "enough_data": bool(enough), "since": first}


def r3(store: JobStore, days: int, *, now: float) -> Dict[str, Any]:
    cutoff = now - days * DAY
    remote = store.remote_seconds_since(cutoff) / 60.0
    local = sum(minutes for _uid, minutes, _o in store.episodes_since(cutoff))
    return {"window_days": days, "remote_minutes": round(remote, 1), "local_minutes": round(local, 1), "share": _share(remote, remote + local)}


def guard(store: JobStore, *, now: float) -> Dict[str, Any]:
    cutoff = now - P3_WINDOW_DAYS * DAY
    calls = len(store.request_kinds_since(cutoff, store.marked_projects()))
    return {"window_days": P3_WINDOW_DAYS, "gave_way": precheck_learn.giveways_since(store, cutoff), "delegate_calls": calls}


def load(store: JobStore, *, now: float) -> Dict[str, Any]:
    hour = int(now // 3600) - (LOAD_HOURS - 1)
    return {"hours": store.load_hours_since(hour)}


def report(store: JobStore, days: int, *, now: float) -> Dict[str, Any]:
    days = max(1, min(KEEP_DAYS, int(days)))
    return {"days": days, "p3": p3(store, now=now), "r3": r3(store, days, now=now), "guard": guard(store, now=now), "load": load(store, now=now)}

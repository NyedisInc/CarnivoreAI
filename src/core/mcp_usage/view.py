
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from src.core.mcp_usage import store as usage_store

SPARK_DAYS = 7


def _utc(now: Optional[datetime]) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _day_counts(store: usage_store.UsageStore, first_day: str, last_day: str) -> Dict[str, Dict[str, int]]:
    per: Dict[str, Dict[str, int]] = {}
    for day, tool, _kind, _outcome, calls in store.rows_between(first_day, last_day):
        per.setdefault(tool, {})[day] = per.get(tool, {}).get(day, 0) + calls
    return per


def reset(registered: Iterable[str], now: Optional[datetime] = None, store: Optional[usage_store.UsageStore] = None) -> str:
    store = store or usage_store.get_store()
    moment = _utc(now)
    day = moment.date().isoformat()
    baseline = {tool: days[day] for tool, days in _day_counts(store, day, day).items() if days.get(day)}
    stamp = moment.isoformat(timespec="seconds")
    store.set_view_reset(stamp, day, baseline)
    return stamp


def counts(registered: Iterable[str], now: Optional[datetime] = None,
           store: Optional[usage_store.UsageStore] = None) -> Dict[str, Any]:
    store = store or usage_store.get_store()
    today = _utc(now).date()
    days = [(today - timedelta(days=SPARK_DAYS - 1 - i)).isoformat() for i in range(SPARK_DAYS)]
    held = store.get_view_reset()
    reset_day = held[1] if held else ""
    baseline = held[2] if held else {}
    per = _day_counts(store, reset_day or "0000-00-00", today.isoformat())
    out: Dict[str, Dict[str, Any]] = {}
    for tool in set(registered) | set(per):
        series = {day: max(0, n - (baseline.get(tool, 0) if day == reset_day else 0)) for day, n in per.get(tool, {}).items()}
        out[tool] = {"calls": sum(series.values()), "daily": [series.get(day, 0) for day in days]}
    return {"since": held[0] if held else None, "days": days, "tools": out}

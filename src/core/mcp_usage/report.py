
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.cplugs.sdk import old_names as sdk_old_names
from src.core.mcp_usage import store as usage_store

MAX_DAYS = usage_store.RETENTION_DAYS
DEFAULT_DAYS = 30
OLD_NAME_RECENT_DAYS = 7


def build(days: int, registered: Iterable[str], store: Optional[usage_store.UsageStore] = None,
          now: Optional[datetime] = None) -> Dict[str, Any]:
    store = store or usage_store.get_store()
    days = max(1, min(int(days), MAX_DAYS))
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    first = today - timedelta(days=days - 1)
    names = set(registered)
    per: Dict[str, Dict[str, Any]] = {}
    for _day, tool, kind, outcome, calls in store.rows_between(first.isoformat(), today.isoformat()):
        row = per.setdefault(tool, {"total": 0, "by_caller_kind": {}, "by_outcome": {}})
        row["total"] += calls
        row["by_caller_kind"][kind] = row["by_caller_kind"].get(kind, 0) + calls
        row["by_outcome"][outcome] = row["by_outcome"].get(outcome, 0) + calls
    last = store.last_called_days()
    tools = []
    for tool in sorted(names | set(per)):
        row = per.get(tool, {"total": 0, "by_caller_kind": {}, "by_outcome": {}})
        tools.append({"tool": tool, "registered": tool in names, **row, "last_called_day": last.get(tool)})
    return {"window": {"from": first.isoformat(), "to": today.isoformat(), "days": days}, "tools": tools,
            "zero_call_tools": sorted(t for t in names if t not in per), "old_names": old_names_block(store, first, today)}


def old_names_block(store: usage_store.UsageStore, first: date, today: date) -> List[Dict[str, Any]]:
    recent_from = (today - timedelta(days=OLD_NAME_RECENT_DAYS - 1)).isoformat()
    per: Dict[Tuple[str, str], Dict[str, Any]] = {
        (kind, name): {"total": 0, "calls_7d": 0, "by_via": {}}
        for kind, names in sdk_old_names.declared().items() for name in names}
    for day, kind, name, via, calls in store.old_names_between(first.isoformat(), today.isoformat()):
        row = per.setdefault((kind, name), {"total": 0, "calls_7d": 0, "by_via": {}})
        row["total"] += calls
        row["calls_7d"] += calls if day >= recent_from else 0
        row["by_via"][via] = row["by_via"].get(via, 0) + calls
    last = store.old_names_last_days()
    return [{"kind": kind, "name": name, **row, "last_used_day": last.get((kind, name))} for (kind, name), row in sorted(per.items())]

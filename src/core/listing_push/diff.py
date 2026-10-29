
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

KeyedRows = List[Tuple[str, Dict[str, Any]]]


def keyed(rows: Sequence[Dict[str, Any]], key_of: Callable[[Dict[str, Any]], Optional[str]]) -> KeyedRows:
    seen: set = set()
    out: KeyedRows = []
    for row in rows:
        key = key_of(row)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((str(key), row))
    return out


CLOCK_DERIVED = frozenset({("stats", "uptime_seconds")})


def _row_change(old: Dict[str, Any], new: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fields: Dict[str, Any] = {}
    nested: Dict[str, Dict[str, Any]] = {}
    for name, value in new.items():
        if name not in old:
            fields[name] = value
            continue
        before = old[name]
        if before == value:
            continue
        if isinstance(before, dict) and isinstance(value, dict) and before.keys() == value.keys():
            moved = {k: v for k, v in value.items()
                     if before.get(k) != v and (name, k) not in CLOCK_DERIVED}
            if moved:
                nested[name] = moved
        else:
            fields[name] = value
    drop = [name for name in old if name not in new]
    if not fields and not nested and not drop:
        return None
    change: Dict[str, Any] = {}
    if fields:
        change["fields"] = fields
    if nested:
        change["nested"] = nested
    if drop:
        change["drop"] = drop
    return change


def diff(previous: Optional[KeyedRows], current: KeyedRows) -> Optional[Dict[str, Any]]:
    old = dict(previous or [])
    upsert: List[Dict[str, Any]] = []
    for key, row in current:
        if key not in old:
            upsert.append({"key": key, "fields": row})
            continue
        change = _row_change(old[key], row)
        if change is not None:
            upsert.append({"key": key, **change})
    current_keys = [key for key, _ in current]
    present = set(current_keys)
    remove = [key for key, _ in (previous or []) if key not in present]
    previous_keys = [key for key, _ in (previous or [])]
    out: Dict[str, Any] = {}
    if upsert:
        out["upsert"] = upsert
    if remove:
        out["remove"] = remove
    if current_keys != previous_keys:
        out["order"] = current_keys
    return out or None

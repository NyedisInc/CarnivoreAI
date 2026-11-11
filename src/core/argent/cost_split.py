
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from src.core.argent import timeline

WATCH_TTL = 300.0
MAX_AGENTS = 200
SHORT_ID = 8

_watches: Dict[str, Tuple[float, frozenset]] = {}


def watch(client_id: str, row_ids: Iterable[str], now: float) -> bool:
    before = watched_rows(now)
    rows = frozenset(str(r) for r in row_ids)
    if rows:
        _watches[client_id] = (now + WATCH_TTL, rows)
    else:
        _watches.pop(client_id, None)
    return bool(watched_rows(now) - before)


def watched_rows(now: float) -> Set[str]:
    for key in [k for k, (until, _r) in _watches.items() if until <= now]:
        del _watches[key]
    return set().union(*(rows for _until, rows in _watches.values())) if _watches else set()


def clear() -> None:
    _watches.clear()


def short_id(agent_id: str) -> str:
    return agent_id[:SHORT_ID]


def rows(body: Optional[Mapping[str, Any]], declared: List[Dict[str, str]], names: Mapping[str, str]) -> Optional[List[Dict[str, Any]]]:
    items = body.get("items") if body else None
    if not isinstance(items, list):
        return None
    out: List[Dict[str, Any]] = []
    for r in items:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str):
            continue
        agent = r["id"]
        micros = r.get("cost_micros")
        out.append({"agent_id": agent, "name": None if agent == "" else (names.get(agent) or short_id(agent)),
                    "item_id": timeline.effective(declared, agent),
                    "cost_micros": micros if isinstance(micros, int) and not isinstance(micros, bool) else None})
    out.sort(key=lambda a: (a["agent_id"] != "", a["agent_id"]))
    return out[:MAX_AGENTS]

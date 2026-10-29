
from __future__ import annotations

import time
from typing import Dict, Iterable, Optional, Tuple

from src.core.swarm import push

WINDOW_S = 8.0
KINDS = ("talking", "escalating", "learning", "promoted", "done")

_marks: Dict[int, Tuple[str, float, Optional[int]]] = {}


def mark(agent_id: int, kind: str, *, talking_with: Optional[int] = None, now: Optional[float] = None) -> None:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    _marks[int(agent_id)] = (kind, time.time() if now is None else now, talking_with)
    push.notify_roster()


def mark_talking(agent_ids: Iterable[int]) -> None:
    ids = sorted(set(int(i) for i in agent_ids))
    if len(ids) == 2:
        mark(ids[0], "talking", talking_with=ids[1])
        mark(ids[1], "talking", talking_with=ids[0])


def current(agent_id: int, now: Optional[float] = None) -> Dict[str, object]:
    found = _marks.get(int(agent_id))
    moment = time.time() if now is None else now
    if found is None or moment - found[1] > WINDOW_S:
        return {"activity": None, "activity_at": None, "talking_with": None}
    return {"activity": found[0], "activity_at": found[1], "talking_with": found[2] if found[0] == "talking" else None}


def clear() -> None:
    _marks.clear()

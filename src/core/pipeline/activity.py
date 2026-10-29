
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from src.core.pipeline import recent
from src.core.pipeline.observe import TRIGGER_LIVE, Waiting

QUEUE_LIMIT: int = 8
SHORT_ID_CHARS: int = 8

Lookup = Callable[[Optional[str]], Optional[recent.Area]]


@dataclass(frozen=True)
class InFlight:

    conversation_id: str
    family: str
    trigger: str
    plugins: Tuple[str, ...]
    started: float


def area_fields(conversation_id: Optional[str], trigger: Optional[str], lookup: Lookup) -> Dict[str, Any]:
    area: Optional[recent.Area] = recent.MACHINE
    if trigger == TRIGGER_LIVE:
        area = lookup(conversation_id)
    unnamed = area is None
    area = area or recent.MACHINE
    return {"scope": area.scope, "session_uuid": area.session_uuid, "session": area.session,
            "project_id": area.project_id, "project": area.project,
            "conversation": ((conversation_id or "")[:SHORT_ID_CHARS] or None) if unnamed else None}


def running_rows(current: Optional[InFlight], rebuilding: Mapping[str, float], *, now: float, wall: float,
                 lookup: Lookup) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if current is not None:
        took = max(0.0, now - current.started)
        place = area_fields(current.conversation_id, current.trigger, lookup)
        for plugin in current.plugins:
            rows.append({"plugin": plugin, "kind": recent.KIND_DELIVERY, **place, "family": current.family,
                         "trigger": current.trigger, "started_at": round(wall - took, 3), "running_s": round(took, 3)})
    for plugin, began in rebuilding.items():
        rows.append({"plugin": plugin, "kind": recent.KIND_REBUILD, **area_fields(None, None, lookup), "family": None,
                     "trigger": recent.KIND_REBUILD, "started_at": round(began, 3),
                     "running_s": round(max(0.0, wall - began), 3)})
    return rows


def queue_rows(waiting: Sequence[Waiting], total: int, *, now: float, wall: float, lookup: Lookup) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for key in waiting:
        due_in = key.eligible_at - now
        items.append({"plugins": list(key.plugins), **area_fields(key.conversation_id, key.trigger, lookup),
                      "family": key.family, "trigger": key.trigger, "backoff": key.backoff,
                      "marked_at": round(wall - max(0.0, now - key.first_dirty), 3),
                      "waited_s": round(max(0.0, now - key.first_dirty), 3),
                      "due_at": round(wall + due_in, 3) if due_in > 0 else None})
    return {"items": items, "total": max(int(total), len(items))}

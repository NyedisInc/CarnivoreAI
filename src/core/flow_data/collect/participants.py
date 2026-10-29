
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SEED_ITEM = "huddle_item"
SEED_SESSION = "session"
SEED_KINDS = (SEED_ITEM, SEED_SESSION)
DEFAULT_TAIL_S = 1800.0
SESSION_WINDOW_S = 6 * 3600.0
MAX_PARTICIPANTS = 24
MAX_DEPTH = 3
REACH_LEAD_S = 120.0
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class SeedNotFound(LookupError):
    pass


@dataclass
class Participants:

    seed: Dict[str, Any]
    start: float
    end: float
    reach: Dict[str, float] = field(default_factory=dict)
    depth: Dict[str, int] = field(default_factory=dict)
    item_ids: List[int] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def is_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.match(value))


def _item_window(data: Dict[str, Any], start: Optional[float], end: Optional[float], now: float) -> Tuple[float, float]:
    item = data["item"]
    times = [item["created_at"], item["updated_at"], *(m["created_at"] for m in data["messages"]), *(e["at"] for e in data["card_events"])]
    return (start if start is not None else item["created_at"]), (end if end is not None else min(max(times) + DEFAULT_TAIL_S, now))


def current_window(activity: Any, seed_kind: str, seed_id: str, start: Optional[float], end: Optional[float], now: float) -> Optional[Tuple[float, float]]:
    if seed_kind != SEED_ITEM:
        return None
    try:
        data = activity.huddle_item(int(seed_id))
    except (TypeError, ValueError):
        return None
    return None if data is None else _item_window(data, start, end, now)


def resolve(activity: Any, seed_kind: str, seed_id: str, start: Optional[float], end: Optional[float],
            now: float) -> Participants:
    if seed_kind == SEED_ITEM:
        try:
            item_id = int(seed_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("a task manager item seed is an item number") from exc
        data = activity.huddle_item(item_id)
        if data is None:
            raise SeedNotFound(f"huddle item {item_id} does not exist")
        item = data["item"]
        lo, hi = _item_window(data, start, end, now)
        keys = {item["created_by"], *(m["author_key"] for m in data["messages"]), *(e["by"] for e in data["card_events"])}
        seed = {"kind": seed_kind, "id": str(item_id), "title": str(item.get("title") or item["text"])[:120], "list": item["list_key"]}
        if item.get("github_issue"):
            seed["github_issue"] = str(item["github_issue"])[:200]
        result = Participants(seed, lo, hi, item_ids=[item_id])
        found = sorted(k for k in keys if is_uuid(k))
    elif seed_kind == SEED_SESSION:
        rows = activity.sessions([str(seed_id)])
        if not rows:
            raise SeedNotFound(f"no session matches {seed_id}")
        hi = end if end is not None else now
        lo = start if start is not None else hi - SESSION_WINDOW_S
        result = Participants({"kind": seed_kind, "id": str(seed_id), "title": rows[0].get("title") or rows[0].get("tmux_name") or ""}, lo, hi)
        found = [rows[0]["session_uuid"]]
    else:
        raise ValueError(f"seed kind must be one of {SEED_KINDS}")
    if hi <= lo:
        raise ValueError("the window is empty")
    for uuid in found:
        result.reach[uuid], result.depth[uuid] = lo, 0
    if not found:
        result.warnings.append("the seed names no session; the chart will be empty")
    return result


def walk(result: Participants, messages: List[Dict[str, Any]]) -> None:
    for _ in range(MAX_DEPTH):
        grew = False
        for m in messages:
            s, r, t = m.get("sender_uuid"), m.get("receiver_uuid"), m["created_at"]
            for here, there in ((s, r), (r, s)):
                if not here or not there or here not in result.reach or t < result.reach[here]:
                    continue
                if there in result.reach:
                    if t < result.reach[there]:
                        result.reach[there], grew = t, True
                elif len(result.reach) >= MAX_PARTICIPANTS:
                    note = f"stopped at {MAX_PARTICIPANTS} sessions"
                    if note not in result.warnings:
                        result.warnings.append(note)
                else:
                    result.reach[there], result.depth[there], grew = t, result.depth[here] + 1, True
        if not grew:
            return
    if any(v >= MAX_DEPTH for v in result.depth.values()) and f"stopped at {MAX_DEPTH} hops" not in result.warnings:
        result.warnings.append(f"stopped at {MAX_DEPTH} hops")

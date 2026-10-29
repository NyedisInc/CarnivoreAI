
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence, Union

CATEGORIES = ("conversation", "result", "question", "important", "dealt", "handed_off", "paused", "resumed",
              "reorder_suggested", "reordered", "auto_done", "validated", "validation_failed", "waiting_for_slot",
              "ready_to_validate", "card_created", "learned", "receipt", "traffic", "info")
DEFAULT_SHOWN = ("conversation", "result", "question", "important")
NEVER_MUTED = ("conversation",)
EVENT_CATEGORY: Mapping[str, str] = {
    "reported": "result", "accepted": "result", "asked": "question", "escalated": "question", "answered": "receipt",
    "learned": "learned", "spawned": "info", "promoted": "info",
}
CARD_REF_PREFIX = "card:"
REPORT_PREFIX = "report:"
IMPORTANT_PREFIXES = ("alert:", "wake_refused:", "wake_failed:", "stuck:", "dead:")


def card_ref(category: str, card_id: Union[int, str]) -> str:
    if category not in CATEGORIES:
        raise ValueError(f"unknown chat category {category!r}")
    return f"{CARD_REF_PREFIX}{category}:{card_id}"


def category_of_ref(swarm_ref: str) -> str:
    if not swarm_ref.startswith(CARD_REF_PREFIX):
        return ""
    category = swarm_ref[len(CARD_REF_PREFIX):].split(":", 1)[0]
    if category not in CATEGORIES:
        raise ValueError(f"unknown chat category {category!r}")
    return category


def derive(entry: Mapping[str, Any]) -> str:
    stored = entry.get("category")
    if stored:
        return str(stored)
    kind = entry.get("kind")
    if kind in ("owner", "agent"):
        return "conversation"
    if kind == "traffic":
        return "traffic"
    if kind == "event":
        return EVENT_CATEGORY.get(str(entry.get("event")), "info")
    if kind == "card":
        ref = str((entry.get("item") or {}).get("swarm_ref") or "")
        if entry.get("card") in ("question", "review"):
            return "question"
        if ref.startswith(REPORT_PREFIX) or entry.get("card") == "done":
            return "result"
        if ref.startswith(IMPORTANT_PREFIXES):
            return "important"
        return "card_created" if not ref else "info"
    return "info"


def check_muted(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("swarm_chat_muted must be a list of category names")
    allowed = [c for c in CATEGORIES if c not in NEVER_MUTED]
    bad = [v for v in value if v not in allowed]
    if bad:
        raise ValueError(f"swarm_chat_muted may name only {allowed}, not {bad}")
    return list(dict.fromkeys(value))


def is_shown(category: str, muted: Optional[Sequence[str]]) -> bool:
    if category in NEVER_MUTED:
        return True
    return category in DEFAULT_SHOWN if muted is None else category not in muted

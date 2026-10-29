
from __future__ import annotations

from dataclasses import dataclass
from typing import Collection, Mapping, Optional, Sequence, Tuple

from src.cplugs.huddle import lane

BY_OWNER = "owner"
BY_AUTO = "auto"
BY_SESSION = "session"
BY_AGENT = "agent"
BY_FALLBACK = "fallback"
BY_PINNED = "pinned"
LEAD_BY = (BY_OWNER, BY_AUTO, BY_SESSION, BY_AGENT, BY_FALLBACK, BY_PINNED)
FALLBACK_PREFIX = "swarm:"
VACANT_EMPTY = "empty"
VACANT_GONE = "gone"


@dataclass(frozen=True)
class Seat:

    list_key: str
    lead_key: str = ""
    lead_by: str = ""
    lead_at: float = 0.0
    ever_led: bool = False


@dataclass(frozen=True)
class Candidate:

    key: str
    created: float
    dnd: bool = False


def standing(seat: Seat, live_keys: Collection[str], asleep_keys: Collection[str],
             present_keys: Collection[str] = ()) -> Tuple[Optional[str], Optional[str]]:
    if not seat.lead_key:
        return None, VACANT_EMPTY
    if seat.lead_key in live_keys or seat.lead_key in asleep_keys or seat.lead_key in present_keys:
        return seat.lead_key, None
    return None, VACANT_GONE


def is_pinned(seat: Seat, agent_key: Optional[str]) -> bool:
    return seat.lead_by == BY_PINNED and bool(seat.lead_key) and seat.lead_key != agent_key


def auto_pick(seat: Seat, candidates: Sequence[Candidate]) -> Optional[str]:
    if seat.ever_led:
        return None
    eligible = [c for c in candidates if not c.dnd]
    return min(eligible, key=lambda c: (c.created, c.key)).key if eligible else None


def may_take(seat: Seat, live_keys: Collection[str], asleep_keys: Collection[str], caller_key: str, present_keys: Collection[str] = ()) -> bool:
    holder, _reason = standing(seat, live_keys, asleep_keys, present_keys)
    return holder is None or holder == caller_key


def fallback_key(agent_id: int) -> str:
    return f"{FALLBACK_PREFIX}{agent_id}"


def fallback_agent_id(key: str) -> Optional[int]:
    tail = key[len(FALLBACK_PREFIX):] if key.startswith(FALLBACK_PREFIX) else ""
    return int(tail) if tail.isdigit() else None


def may_offer(row: Mapping) -> bool:
    return not (row["lane"] == lane.SWARM or row["card_holder"] is not None or row["card_dealt_to"] is not None)

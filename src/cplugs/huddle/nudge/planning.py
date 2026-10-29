
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Collection, Dict, List, Mapping, Optional, Sequence

from src.cplugs.huddle import lifecycle

OPEN, WORKING, AGENT_IDLE = lifecycle.OPEN, lifecycle.WORKING, lifecycle.AGENT_IDLE
SWEEP_DIVISOR, SWEEP_MIN_S, SWEEP_MAX_S = 6.0, 60.0, 300.0
IDLE_STATES = ("idle", "finished_unread")

Position = Callable[..., str]


def effective(session_pref: Optional[bool], project_on: bool) -> bool:
    return project_on if session_pref is None else bool(session_pref)


def sweep_period_s(minutes: float) -> float:
    return min(max(minutes * 60.0 / SWEEP_DIVISOR, SWEEP_MIN_S), SWEEP_MAX_S)


@dataclass(frozen=True)
class Candidate:

    row: Mapping[str, Any]
    status: str
    last_activity: float
    basis: str
    pickup: bool = False
    session_key: str = ""
    session_state: Optional[str] = None
    session_last: Optional[float] = None

    @property
    def id(self) -> int:
        return self.row["id"]


@dataclass(frozen=True)
class Plan:

    nudge: List[Candidate]
    stall: List[Candidate]


def plan(candidates: Sequence[Candidate], *, now: float, interval_s: float, tries: int, session_state: Optional[str],
         list_held: bool, position: Position) -> Plan:
    out = Plan([], [])
    for cand in candidates:
        owned = bool(cand.session_key)
        state = cand.session_state if owned else session_state
        if owned and state not in IDLE_STATES:
            continue
        quiet_since = max(cand.last_activity, cand.session_last or 0.0) if owned else cand.last_activity
        idle = now - quiet_since >= interval_s
        if position(cand.row, cand.status, list_held=list_held, session_state=state, idle=idle) != AGENT_IDLE:
            continue
        count = cand.row["nudge_count"] or 0
        anchor = max(quiet_since, cand.row["nudge_last_at"] or 0.0)
        if now < anchor + interval_s * (count + 1):
            continue
        (out.nudge if count < tries else out.stall).append(cand)
    return out


def owner_of(row: Mapping[str, Any]) -> str:
    keys = row.keys()
    return (row["claimant"] if "claimant" in keys else "") or (row["owner_session_key"] if "owner_session_key" in keys else "") or ""


def plan_lost(candidates: Sequence[Candidate], *, live_keys: Collection[str], now: float, interval_s: float, list_held: bool,
              position: Position) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    for cand in candidates:
        holder = owner_of(cand.row)
        if not holder or holder in live_keys:
            continue
        idle = now - cand.last_activity >= interval_s
        if idle and position(cand.row, cand.status, list_held=list_held, session_state=None, idle=idle) == AGENT_IDLE:
            out.setdefault(holder, []).append(cand.id)
    return out

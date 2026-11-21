
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from src.core.pack.machines.roster_doc import Roster
from src.core.pack.machines.settings_doc import PackSettings

ARM_SECONDS = 300.0
RECLAIM_SECONDS = ARM_SECONDS
ROUND_SECONDS = 30.0
GAP_SECONDS = 90.0
WALK_FRESH_SECONDS = 60.0
ISSUED_SKEW_SECONDS = 600
SECURITY_FIELDS: Tuple[str, ...] = ()

OK = "ok"


class ObservedSpan:

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._first: Optional[float] = None
        self._last: Optional[float] = None

    def failed(self) -> None:
        now = self._clock()
        if self._last is None or now - self._last > GAP_SECONDS:
            self._first = now
        self._last = now

    def reached(self) -> None:
        self._first = self._last = None

    def seconds(self) -> float:
        if self._first is None or self._last is None or self._clock() - self._last > GAP_SECONDS:
            return 0.0
        return self._last - self._first


@dataclass(frozen=True)
class Peer:

    reachable: bool
    can_claim: bool = False


@dataclass(frozen=True)
class Walk:

    at: float
    peers: Dict[str, Peer] = field(default_factory=dict)


@dataclass(frozen=True)
class Standing:

    now: float
    alpha_span: float = 0.0
    walk: Optional[Walk] = None
    silent: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class HomeState:

    home_override: Optional[str] = None
    last_home: Optional[Tuple[int, int]] = None


def effective_home(roster: Optional[Roster], state: HomeState) -> Optional[str]:
    return state.home_override or (roster.home if roster is not None else None)


def is_interim(master: str, roster: Optional[Roster], state: HomeState) -> bool:
    if roster is None:
        return False
    return master not in (roster.home, state.home_override)


def content_alpha(master: str, interim: bool) -> Optional[str]:
    return None if interim else master


def rank(roster: Roster, iid: str) -> Optional[int]:
    order = roster.order()
    return order.index(iid) if iid in order else None


def eligible(roster: Roster, iid: str) -> bool:
    entry = roster.entry(iid)
    return entry is not None and (entry.takeover_eligible or iid == roster.home)


def blockers_above(roster: Roster, iid: str, walk: Walk) -> List[str]:
    above = rank(roster, iid)
    if above is None:
        return []
    out = []
    for other in roster.order()[:above]:
        peer = walk.peers.get(other)
        if eligible(roster, other) and peer is not None and peer.reachable and peer.can_claim:
            out.append(other)
    return out


def _walk_fresh(walk: Optional[Walk], now: float) -> bool:
    return walk is not None and 0 <= now - walk.at <= WALK_FRESH_SECONDS


def may_claim(*, roster: Roster, self_id: str, alpha: str, alpha_span: float, walk: Optional[Walk], now: float) -> Tuple[bool, str]:
    if self_id == alpha:
        return False, "already alpha"
    if not eligible(roster, self_id):
        return False, "not eligible"
    if alpha_span < ARM_SECONDS:
        return False, "alpha not observed down long enough"
    if not _walk_fresh(walk, now):
        return False, "no fresh walk"
    assert walk is not None
    if walk.peers.get(alpha, Peer(False)).reachable:
        return False, "alpha reachable"
    if blockers_above(roster, self_id, walk):
        return False, "a higher ranked computer is alive"
    return True, OK


def member_accepts(*, roster: Roster, self_id: str, self_can_claim: bool, held_alpha: str, claimant: str, claim_generation: int,
                   held_generation: int, standing: Standing) -> Tuple[bool, str]:
    if not eligible(roster, claimant):
        return False, "claimant is not eligible"
    if claim_generation <= held_generation:
        return False, "generation not above held"
    if standing.alpha_span < ARM_SECONDS:
        return False, "own alpha span too short"
    if not _walk_fresh(standing.walk, standing.now):
        return False, "no fresh walk"
    walk = standing.walk
    assert walk is not None
    if walk.peers.get(held_alpha, Peer(False)).reachable:
        return False, "alpha reachable from here"
    walk = Walk(walk.at, {**walk.peers, self_id: Peer(True, self_can_claim)})
    if blockers_above(roster, claimant, walk):
        return False, "a higher ranked computer is alive"
    return True, OK


def content_check(*, held_roster: Roster, new_roster: Roster, held_doc: PackSettings, new_doc: PackSettings) -> Tuple[bool, str]:
    if held_roster.home != new_roster.home:
        return False, "home changed"
    if held_roster.order() != new_roster.order():
        return False, "membership or order changed"
    for old, new in zip(held_roster.computers, new_roster.computers):
        if (old.fed_public_key, old.cert, old.next_cert) != (new.fed_public_key, new.cert, new.next_cert):
            return False, "a pin or key changed"
        if old.takeover_eligible != new.takeover_eligible:
            return False, "eligibility changed"
        if old.relay_id != new.relay_id:
            return False, "a relay id changed"
    for name in SECURITY_FIELDS:
        if getattr(held_doc, name) != getattr(new_doc, name):
            return False, f"security field {name} changed"
    return True, OK


def home_document_ok(*, state: HomeState, interim: bool, generation: int, issued_at: int, held_generation: int = 0) -> Tuple[bool, str]:
    if not interim:
        return False, "not interim: plain rules"
    if state.last_home is None:
        return (True, OK) if generation > held_generation else (False, "generation not above the held one")
    last_gen, last_at = state.last_home
    if generation <= last_gen:
        return False, "generation not above the last home document"
    if issued_at < last_at - ISSUED_SKEW_SECONDS:
        return False, "older than the last home document"
    return True, OK


def reclaim_due(*, self_id: str, roster: Optional[Roster], state: HomeState, master: str, linked_seconds: float) -> bool:
    return (roster is not None and effective_home(roster, state) == self_id and master != self_id
            and linked_seconds >= RECLAIM_SECONDS)


def meeting_decision(*, roster: Roster, state: HomeState, self_id: str, self_generation: int, other: str, other_generation: int,
                     silent_seconds: float) -> Tuple[str, str]:
    home = effective_home(roster, state)
    if self_id == home:
        return "stay", "this computer is home"
    if other == home:
        return "stay", "wait for the home's reclaim"
    if not eligible(roster, other):
        return "refuse", "the other is not eligible"
    if silent_seconds < ARM_SECONDS:
        return "refuse", "linked to it inside the arming window"
    mine, theirs = rank(roster, self_id), rank(roster, other)
    if theirs is None:
        return "refuse", "the other is not listed"
    if other_generation > self_generation or (other_generation == self_generation and (mine is None or theirs < mine)):
        return "step_down", "the other wins"
    return "stay", "this computer wins"


from __future__ import annotations

import hashlib
from typing import Collection, Dict, FrozenSet, Iterable, List, Optional

from src.core.pack.machines import capabilities
from src.core.pack.machines.roster_v2 import RosterV2

STANDING_LINKS = 8


def pair_key(a: str, b: str) -> str:
    return hashlib.sha256((min(a, b) + max(a, b)).encode()).hexdigest()


def own_switch(lst: object, self_iid: str) -> str:
    if not isinstance(lst, RosterV2):
        return "no_list"
    if self_iid == lst.alpha:
        return "alpha"
    own = lst.entry(self_iid)
    return "on" if capabilities.mesh_on() and own is not None and own.mesh and own.link_peers else "off"


def eligible_ids(lst: object, self_iid: str) -> List[str]:
    if own_switch(lst, self_iid) != "on":
        return []
    assert isinstance(lst, RosterV2)
    return [c.install_id for c in lst.computers if c.install_id not in (self_iid, lst.alpha) and c.mesh and c.link_peers]


def choose_links(lst: object, self_iid: str, *, reachable: Optional[Collection[str]] = None, connected: Iterable[str] = (),
                 excluded: Iterable[str] = (), cap: Optional[int] = None) -> List[str]:
    cap = STANDING_LINKS if cap is None else cap
    eligible = set(eligible_ids(lst, self_iid))
    if not eligible or not isinstance(lst, RosterV2):
        return []
    live, bad = set(connected), set(excluded)
    order = lst.order()
    kept = sorted(eligible & live, key=order.index)[:cap]
    rest = sorted(eligible - live - bad, key=lambda p: (reachable is not None and p not in reachable, bool(lst.entry(p).laptop), pair_key(self_iid, p)))
    return kept + rest[:max(0, cap - len(kept))]


class Exclusions:

    EXCLUDE_AFTER_SECONDS = 120.0
    EXCLUDE_SECONDS = 600.0

    def __init__(self) -> None:
        self._bad_since: Dict[str, float] = {}
        self._until: Dict[str, float] = {}

    def observe(self, iid: str, bad: bool, now: float) -> None:
        if bad:
            self._bad_since.setdefault(iid, now)
        else:
            self._bad_since.pop(iid, None)

    def excluded(self, now: float) -> FrozenSet[str]:
        for iid, since in list(self._bad_since.items()):
            if now - since >= self.EXCLUDE_AFTER_SECONDS:
                self._until[iid] = now + self.EXCLUDE_SECONDS
                del self._bad_since[iid]
        for iid, until in list(self._until.items()):
            if now >= until:
                del self._until[iid]
        return frozenset(self._until)

    def forget(self, iid: str) -> None:
        self._bad_since.pop(iid, None)
        self._until.pop(iid, None)

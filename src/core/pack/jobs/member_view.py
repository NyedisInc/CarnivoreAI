
from __future__ import annotations

import asyncio
import re
import dataclasses
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple

import structlog

from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.jobs import member_link, target
from src.core.pack.jobs.place import PlaceView
from src.core.pack.jobs.types import CAP_JOBS
from src.core.pack.machines import capabilities, can_block, roster
from src.core.pack.meshdata import gossip
from src.core.pack.placement import explain, rule
from src.core.pack.transport import blobs

log = structlog.get_logger(__name__)

CARD_MAX_AGE_S = 2 * gossip.HEARTBEAT_SECONDS + 60
LOOK_FRESH_S = roster.STALE_SECONDS
LOOK_BUDGET_S = 5.0
MAX_LOOK_DIALS = 2
MAX_JOBS_PER_MEMBER = 4
NO_CHAIN = "work this computer received from another computer is never handed on"
CACHE_MAX = 256
_WIRE_ERRORS = (PeerUnreachable, PeerRefused, asyncio.TimeoutError, OSError)
Entry = Tuple[float, Optional[Dict[str, Any]], str, Optional[List[str]]]


@dataclass
class Facts:

    members: List[str] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)
    self_one_way: bool = False
    home: Optional[str] = None
    counterparts: Set[str] = field(default_factory=set)
    cards: Dict[str, int] = field(default_factory=dict)
    star: Set[str] = field(default_factory=set)
    linked: Set[str] = field(default_factory=set)
    free_on_demand: int = 0
    held: Dict[str, int] = field(default_factory=dict)
    on_demand: Set[str] = field(default_factory=set)


def read_facts(root: str, uid: str, self_iid: str, store: Any) -> Facts:
    from src.core.computers import direction, mesh
    from src.core.federation import mesh_peers
    from src.core.pack.machines import runtime as machines_runtime
    from src.core.pack.relay import member_reach

    wired = machines_runtime.wiring()
    lst = member_reach.held_v2()
    if wired is None or lst is None:
        return Facts()
    members = member_reach.member_ids()
    with closing(wired.open_db()) as conn:
        presence = explain.lookup_project(conn, root, self_iid)
    if presence.present_on is None:
        counterparts: Set[str] = set()
    else:
        counterparts = (presence.present_on - {self_iid}) if presence.home_install_id == self_iid else {presence.home_install_id}
    snap = mesh.snapshot()
    used = sum(1 for link in (snap or {}).get("links", []) if link.get("on_demand"))
    on_demand = {str(link.get("install_id")) for link in (snap or {}).get("links", []) if link.get("on_demand") and not link.get("standing")}
    reg = mesh_peers.REGISTRY
    held: Dict[str, int] = {}
    for rec in store.list_jobs(limit=500, live_only=True):
        if rec.peer_install_id:
            held[rec.peer_install_id] = held.get(rec.peer_install_id, 0) + 1
    return Facts(
        members=members, labels={c.install_id: c.label for c in lst.computers}, self_one_way=direction.listed_one_way(lst, self_iid),
        home=presence.home_install_id, counterparts=counterparts, cards={i: int(c.get("age_s", CARD_MAX_AGE_S + 1)) for i, c in gossip.heard_now().items()},
        star={p.install_id for p in wired.peers()}, linked={i for i in members if reg is not None and reg.capabilities(i) is not None},
        free_on_demand=0 if snap is None else max(0, mesh.MAX_ON_DEMAND - used), held=held, on_demand=on_demand)


async def look_member(iid: str, uid: str, dial: bool) -> Tuple[int, Any]:
    try:
        if dial:
            client, _why = await member_link.connect_for(iid)
        else:
            client = member_link.client_for(iid)
        if client is None:
            return 0, None
        return await blobs.request_via(client, LOOK_BUDGET_S)("POST", target.JOBS_PATH + "/look", json={"project_uid": uid})
    except _WIRE_ERRORS as exc:
        log.info("pack_member_look_failed", peer=iid[:8], error_type=type(exc).__name__)
        return 0, None


def _caps(iid: str) -> Optional[List[str]]:
    from src.core.federation import mesh_peers

    return mesh_peers.REGISTRY.capabilities(iid) if mesh_peers.REGISTRY is not None else None


@dataclass
class Deps:

    read: Callable[[str, str, str, Any], Facts] = read_facts
    look: Callable[[str, str, bool], Any] = look_member
    caps: Callable[[str], Optional[List[str]]] = _caps
    clock: Callable[[], float] = time.monotonic


def _verdict(status: int, body: Any) -> str:
    if status == 200 and isinstance(body, dict):
        return body["project"] if isinstance(body.get("project"), str) else "unreachable"
    detail = body.get("detail") if isinstance(body, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    ok = status in (400, 403, 404, 409, 422) and isinstance(code, str) and re.fullmatch(r"[a-z_]{1,40}", code)
    return code if ok else "unreachable"


class MemberView:

    def __init__(self, deps: Optional[Deps] = None) -> None:
        self._deps = deps or Deps()
        self._cache: Dict[Tuple[str, str], Entry] = {}

    def _remember(self, key: Tuple[str, str], entry: Entry, now: float) -> None:
        for stale in [k for k, e in self._cache.items() if now - e[0] > LOOK_FRESH_S]:
            del self._cache[stale]
        while len(self._cache) >= CACHE_MAX:
            del self._cache[min(self._cache, key=lambda k: self._cache[k][0])]
        self._cache[key] = entry

    def _fresh(self, iid: str, uid: str, now: float) -> Optional[Entry]:
        entry = self._cache.get((iid, uid))
        return entry if entry is not None and now - entry[0] <= LOOK_FRESH_S else None

    def _entry(self, iid: str, uid: str, now: float, status: int, body: Any) -> Entry:
        caps = self._deps.caps(iid)
        if status == 200 and isinstance(body, dict) and capabilities.has(caps, CAP_JOBS) and capabilities.has(caps, capabilities.CAP_JOBS_MESH):
            snap = body.get("snapshot")
            clean = can_block.clean_received(snap) if roster.snapshot_ok(snap, iid) else None
            return now, clean, _verdict(status, body), list(caps or [])
        return now, None, _verdict(status, body) if status != 200 else "unreachable", list(caps or []) or None

    async def _look_all(self, wanted: List[Tuple[str, bool]], uid: str) -> None:
        now = self._deps.clock()
        tasks = {asyncio.ensure_future(self._deps.look(iid, uid, dial)): iid for iid, dial in wanted}
        done, pending = await asyncio.wait(tasks, timeout=LOOK_BUDGET_S) if tasks else (set(), set())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task, iid in tasks.items():
            status, body = (0, None)
            if task in done:
                failure = task.exception()
                if failure is None:
                    status, body = task.result()
                else:
                    log.warning("pack_member_look_error", peer=iid[:8], error_type=type(failure).__name__)
            self._remember((iid, uid), self._entry(iid, uid, now, status, body), now)

    async def _extend_copies(self, view: PlaceView, root: str, uid: str, store: Any, self_iid: str) -> PlaceView:
        d = self._deps
        try:
            facts = await asyncio.to_thread(d.read, root, uid, self_iid, store)
        except (sqlite3.Error, OSError) as exc:
            log.warning("pack_member_copy_view_unreadable", error_type=type(exc).__name__)
            return view
        if facts.self_one_way or facts.home != self_iid:
            return view
        skip = {self_iid, view.master_id, *facts.star}
        skips: Dict[str, str] = {}
        cands: List[str] = []
        for m in facts.members:
            if m in skip:
                continue
            if m not in facts.linked:
                skips[m] = "not_linked"
            elif m in facts.on_demand:
                skips[m] = "on_demand_only"
            elif not capabilities.has(d.caps(m), capabilities.CAP_JOBS_MESH):
                skips[m] = "older_app"
            elif facts.cards.get(m, CARD_MAX_AGE_S + 1) > CARD_MAX_AGE_S:
                skips[m] = "no_status_card"
            else:
                cands.append(m)
        now = d.clock()
        wanted = [(m, False) for m in cands if self._fresh(m, uid, now) is None]
        if wanted:
            await self._look_all(wanted, uid)
            now = d.clock()
        added: List[rule.MachineInput] = []
        caps: Dict[str, List[str]] = {}
        for iid in cands:
            entry = self._fresh(iid, uid, now)
            snap, verdict = (entry[1], entry[2]) if entry is not None else (None, "unreachable")
            added.append(rule.MachineInput(iid, facts.labels.get(iid, ""), snap, snap is not None, False, facts.home == iid,
                                           iid in facts.counterparts and verdict == "ok", None))
            caps[iid] = list(entry[3] or d.caps(iid) or []) if entry is not None else list(d.caps(iid) or [])
        return dataclasses.replace(view, peers=[*view.peers, *added], caps={**view.caps, **caps}, mesh_members=frozenset(m.install_id for m in added), member_notes={}, copy_skips=skips)

    async def extend(self, view: PlaceView, root: str, uid: str, *, store: Any, self_iid: str, copies: bool = False) -> PlaceView:
        if not member_link.on():
            return view
        if copies:
            return await self._extend_copies(view, root, uid, store, self_iid)
        d = self._deps
        facts = await asyncio.to_thread(d.read, root, uid, self_iid, store)
        if facts.self_one_way:
            return view
        skip = {self_iid, view.master_id, *facts.star}
        cands = [m for m in facts.members if m not in skip and m in facts.counterparts
                 and facts.cards.get(m, CARD_MAX_AGE_S + 1) <= CARD_MAX_AGE_S]
        capped = {m for m in cands if facts.held.get(m, 0) >= MAX_JOBS_PER_MEMBER}
        now = d.clock()
        askable = [m for m in cands if m not in capped]
        live = [m for m in askable if m in facts.linked and capabilities.has(d.caps(m), capabilities.CAP_JOBS_MESH)]
        wanted = [(m, False) for m in live if self._fresh(m, uid, now) is None]
        if not [m for m in askable if m in facts.linked] and facts.free_on_demand > MAX_LOOK_DIALS:
            wanted = [(m, True) for m in [x for x in askable if x not in facts.linked][:MAX_LOOK_DIALS] if self._fresh(m, uid, now) is None]
        if wanted:
            await self._look_all(wanted, uid)
            now = d.clock()
        added: List[rule.MachineInput] = []
        caps: Dict[str, List[str]] = {}
        notes: Dict[str, str] = {}
        for iid in cands:
            entry = self._fresh(iid, uid, now) if iid not in capped else None
            snap, verdict = (entry[1], entry[2]) if entry is not None else (None, "unreachable")
            added.append(rule.MachineInput(iid, facts.labels.get(iid, ""), snap, snap is not None, False, facts.home == iid,
                                           iid in facts.counterparts and verdict == "ok", None))
            caps[iid] = [CAP_JOBS] if iid in capped else list(entry[3] or []) if entry is not None and entry[3] else list(d.caps(iid) or [])
            if iid in capped:
                notes[iid] = f"already holds {MAX_JOBS_PER_MEMBER} jobs from this computer"
            elif verdict not in ("ok", "project_not_here", "unreachable"):
                notes[iid] = f"would not take this project's work ({verdict})"
        return dataclasses.replace(view, peers=[*view.peers, *added], caps={**view.caps, **caps}, mesh_members=frozenset(m.install_id for m in added),
                                   member_notes=notes)


def without_refused_uploads(view: PlaceView, own_scopes: FrozenSet[str]) -> Tuple[PlaceView, bool]:
    if "replica" in own_scopes or not view.mesh_members:
        return view, False
    kept = [p for p in view.peers if p.install_id not in view.mesh_members]
    return dataclasses.replace(view, peers=kept), len(kept) != len(view.peers)


_COPY_VIEW = MemberView()


async def for_copies(view: PlaceView, root: str, uid: str, *, store: Any, self_iid: str) -> PlaceView:
    if not capabilities.mesh_on():
        return view
    return await _COPY_VIEW.extend(view, root, uid, store=store, self_iid=self_iid, copies=True)

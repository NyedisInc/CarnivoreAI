
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import service as task_manager_service
from src.cplugs.huddle.roles import lead
from src.cplugs.huddle.roles.store import RoleStore, SeatTaken
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.session_rows import SessionRowsUnreadable
from src.cplugs.sdk.swarm import SeatRef

logger = structlog.get_logger()

LEAD_RANKS = ("project", "company")


class RolesUnmeasured(Exception):
    """The live or asleep sessions could not be read: nothing about who leads may be decided or shown from this pass."""


@dataclass(frozen=True)
class Roster:
    """What one measurement says, per project list key (digits): the ordinary agent sessions live now, and the stable keys asleep.

    ``live`` maps a list key to its :class:`lead.Candidate` rows (a Swarm agent's body is left out, EXCEPT the project's own project
    agent: that one leads, #1789); ``asleep`` maps a list key to the stable keys on the asleep list; ``labels`` maps a stable key to its
    row's name; ``agents`` is every live Swarm agent (:class:`SeatRef`, ``ctx.swarm.agent_seats``); ``present`` maps a list key to the
    lead keys that are neither live nor asleep in this pass but whose stored row still stands in the project (``lead.standing``);
    ``enclosing`` maps a nested project's list key to the list keys of the projects whose folder encloses its own, nearest first
    (``ctx.projects.enclosing``; measured only while a project agent exists).
    """

    live: Dict[str, List[lead.Candidate]] = field(default_factory=dict)
    asleep: Dict[str, Set[str]] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)
    keys: Dict[str, str] = field(default_factory=dict)
    agents: Tuple[SeatRef, ...] = ()
    present: Dict[str, Set[str]] = field(default_factory=dict)
    enclosing: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def project_agents(self) -> Dict[str, str]:
        return {a.project_key: a.session_uuid or lead.fallback_key(a.agent_id)
                for a in self.agents if a.rank in LEAD_RANKS and a.project_key is not None and not a.body_gone}

    def inherited_agent(self, list_key: str) -> Optional[str]:
        agents = self.project_agents
        if list_key in agents:
            return None
        return next((agents[outer] for outer in self.enclosing.get(list_key, ()) if outer in agents), None)

    @property
    def swarm_keys(self) -> Set[str]:
        return {lead.fallback_key(a.agent_id) for a in self.agents if not a.body_gone}

    def live_keys(self, list_key: str) -> Set[str]:
        return {c.key for c in self.live.get(list_key, ())}

    def asleep_keys(self, list_key: str) -> Set[str]:
        return self.asleep.get(list_key, set())

    def present_keys(self, list_key: str) -> Set[str]:
        return self.present.get(list_key, set())


async def is_swarm_body(ctx: CplugContext, session_id: str) -> bool:
    swarm = task_manager_service.swarm_of(ctx)
    return swarm is not None and await swarm.thread_for_session(session_id) is not None


async def project_agent_keys(ctx: CplugContext) -> Set[str]:
    swarm = task_manager_service.swarm_of(ctx)
    if swarm is None:
        return set()
    return {a.session_uuid or lead.fallback_key(a.agent_id) for a in await asyncio.to_thread(swarm.agent_seats)
            if a.rank in LEAD_RANKS and not a.body_gone}


async def set_dnd(ctx: CplugContext, store: RoleStore, session_key: str, on: bool) -> bool:
    also = await project_agent_keys(ctx) if on else set()
    return await asyncio.to_thread(store.set_dnd, session_key, on, also)


async def measure(ctx: CplugContext, infos: Optional[List[Any]] = None, asleep_rows: Optional[List[Dict[str, Any]]] = None) -> Roster:
    rows = list(await ctx.sessions.list() if infos is None else infos)
    keys = await ctx.sessions.durable_keys(rows)
    swarm = task_manager_service.swarm_of(ctx)
    agents = tuple(await asyncio.to_thread(swarm.agent_seats)) if swarm is not None else ()
    bodies = {a.session_uuid for a in agents if a.session_uuid}
    leads = {a.session_uuid: a.project_key for a in agents if a.rank in LEAD_RANKS and a.session_uuid and not a.body_gone}
    live: Dict[str, List[lead.Candidate]] = {}
    labels: Dict[str, str] = {}
    for info in rows:
        project = getattr(info, "project_id", None)
        if project is None or not task_manager_service.is_agent(info):
            continue
        key = keys.get(info.session.id) or info.session.id
        if key in bodies and leads.get(key) != str(project):  # own project
            continue
        created = getattr(info.session, "created_at", None)
        live.setdefault(str(project), []).append(lead.Candidate(key, created.timestamp() if created is not None else 0.0))
        labels[key] = info.label or info.tmux_session or info.session.id
    asleep: Dict[str, Set[str]] = {}
    sleeper = getattr(ctx.sessions, "asleep", None)
    if sleeper is None:
        raise RolesUnmeasured("this context cannot list the asleep sessions")
    try:
        for record in (asleep_rows if asleep_rows is not None else await sleeper()):
            uuid = record["session_uuid"]
            if uuid in bodies and leads.get(uuid) != str(record["project_id"]):
                continue
            asleep.setdefault(str(record["project_id"]), set()).add(uuid)
            labels.setdefault(uuid, record.get("name") or uuid)
    except (HTTPException, OSError, RuntimeError, KeyError) as exc:
        logger.warning("task_manager_roles_asleep_unreadable", error_type=type(exc).__name__)
        raise RolesUnmeasured("the asleep sessions could not be read") from exc
    for agent in agents:
        labels.setdefault(lead.fallback_key(agent.agent_id), agent.display_name)
    present = await _present(ctx, live, asleep, agents)
    return Roster(live, asleep, labels, keys, agents, present, await _enclosing(ctx, agents))


async def _enclosing(ctx: CplugContext, agents: Tuple[SeatRef, ...]) -> Dict[str, List[str]]:
    if not any(a.rank == "project" and a.project_key and not a.body_gone for a in agents):
        return {}
    try:
        return await asyncio.to_thread(ctx.projects.enclosing)
    except OSError as exc:
        raise RolesUnmeasured("the project folders could not be read") from exc


async def _present(ctx: CplugContext, live: Dict[str, List[lead.Candidate]], asleep: Dict[str, Set[str]],
                   agents: Tuple[SeatRef, ...]) -> Dict[str, Set[str]]:
    seats = await asyncio.to_thread(RoleStore(task_manager_service.store(ctx)).seats)
    wanted = {(s.list_key, s.lead_key) for s in seats.values() if s.lead_key and lead.fallback_agent_id(s.lead_key) is None}
    wanted |= {(a.project_key, a.session_uuid) for a in agents if a.rank in LEAD_RANKS and a.project_key and a.session_uuid and not a.body_gone}
    unseen = {(list_key, key) for list_key, key in wanted
              if key not in asleep.get(list_key, set()) and all(c.key != key for c in live.get(list_key, ()))}
    if not unseen:
        return {}
    try:
        rows = await ctx.sessions.stored_rows(sorted({key for _list, key in unseen}))
    except (SessionRowsUnreadable, PermissionError) as exc:
        raise RolesUnmeasured("the stored session rows could not be read") from exc
    present: Dict[str, Set[str]] = {}
    for list_key, key in unseen:
        row = rows.get(key)
        if row is not None and not row.archived and (row.project_id is None or str(row.project_id) == list_key):
            present.setdefault(list_key, set()).add(key)
    return present


def evaluate(store: RoleStore, roster: Roster) -> Dict[str, lead.Seat]:
    with store.read_scope():
        return _evaluate(store, roster)


def _evaluate(store: RoleStore, roster: Roster) -> Dict[str, lead.Seat]:
    dnd = store.dnd_keys()
    seats = store.seats()
    agents = roster.project_agents
    for list_key, key in agents.items():
        held = seats.get(list_key, lead.Seat(list_key))
        if lead.is_pinned(held, key) and holder_of(held, roster)[0] == held.lead_key:
            continue
        if held.lead_key != key or held.lead_by != lead.BY_AGENT:
            seats[list_key] = store.set_lead(list_key, key, lead.BY_AGENT)
    for list_key, candidates in roster.live.items():
        if list_key in agents:
            continue
        seat = seats.get(list_key, lead.Seat(list_key))
        picked = lead.auto_pick(seat, [lead.Candidate(c.key, c.created, c.key in dnd) for c in candidates])
        if picked is None:
            continue
        try:
            seats[list_key] = store.take_if_vacant(list_key, picked, roster.live_keys(list_key), roster.asleep_keys(list_key), lead.BY_AUTO,
                                                   roster.present_keys(list_key))
        except SeatTaken:
            seats[list_key] = store.seat(list_key)
    return seats


def holder_of(seat: lead.Seat, roster: Roster) -> Tuple[Optional[str], Optional[str]]:
    live = roster.live_keys(seat.list_key)
    if lead.fallback_agent_id(seat.lead_key) is not None:
        live = live | roster.swarm_keys
    inherited = roster.inherited_agent(seat.list_key)
    if inherited is not None:
        live = live | {inherited}
    return lead.standing(seat, live, roster.asleep_keys(seat.list_key), roster.present_keys(seat.list_key))


PREFS_TOPIC = "prefs"


def notify_prefs(ctx: CplugContext) -> None:
    try:
        ctx.notify(PREFS_TOPIC)
    except (RuntimeError, ValueError, AttributeError) as exc:
        ctx.log.warning("task_manager_prefs_notify_failed", error=str(exc))


def seat_view(seat: lead.Seat, roster: Roster) -> Dict[str, Any]:
    holder, reason = holder_of(seat, roster)
    view: Dict[str, Any] = {"session": holder, "name": roster.labels.get(holder) if holder else None, "by": seat.lead_by, "at": seat.lead_at}
    if reason is not None:
        view["vacant_reason"] = reason
    return view

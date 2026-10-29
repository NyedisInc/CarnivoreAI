
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Collection, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import structlog
from fastapi import HTTPException

from src.cplugs.huddle.roles import lead
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.sdk import CplugContext, session_bring_up
from src.cplugs.sdk.swarm import SwarmError

if TYPE_CHECKING:
    from src.cplugs.huddle.store import TaskManagerStore

logger = structlog.get_logger()

REASON_LEAD = "lead"

LIVE, WOKEN, GONE, WAKE_FAILED = "live", "woken", "gone", "wake_failed"
ASLEEP = "asleep"


@dataclass(frozen=True)
class Resolution:

    info: Optional[Any]
    outcome: str

    @property
    def ready(self) -> bool:
        return self.info is not None


async def _swarm_agent(ctx: CplugContext, session_key: str) -> Optional[Tuple[Any, Any]]:
    from src.cplugs.huddle import service  # noqa: PLC0415

    swarm = service.swarm_of(ctx)
    if swarm is None:
        return None
    agent_id = lead.fallback_agent_id(session_key)
    agent = await swarm.agent_by_id(agent_id) if agent_id is not None else await swarm.agent_for_session_uuid(session_key)
    return (swarm, agent) if agent is not None else None


async def _resolve_agent(ctx: CplugContext, swarm: Any, agent: Any) -> Resolution:
    outcome = LIVE
    if agent.session_id is None:
        try:
            await swarm.wake(agent.id, "manual")
        except SwarmError as exc:
            logger.warning("task_manager_route_swarm_wake_failed", agent=agent.id, error=str(exc)[:200])
            return Resolution(None, WAKE_FAILED)
        agent = await swarm.agent_by_id(agent.id)
        outcome = WOKEN
    info = await session_bring_up.find_live(ctx.sessions, agent.session_uuid) if agent is not None and agent.session_uuid else None
    return Resolution(info, outcome) if info is not None else Resolution(None, WAKE_FAILED)


async def resolve(ctx: CplugContext, session_key: str) -> Resolution:
    found = await _swarm_agent(ctx, session_key)
    if found is not None:
        return await _resolve_agent(ctx, *found)
    if lead.fallback_agent_id(session_key) is not None:
        return Resolution(None, GONE)
    ops = ctx.sessions
    info = await session_bring_up.find_live(ops, session_key)
    if info is not None:
        return Resolution(info, LIVE)
    try:
        if not await session_bring_up.is_asleep(ops, session_key):
            return Resolution(None, GONE)
        await session_bring_up.wake_by_uuid(ops, session_key)
    except (HTTPException, session_bring_up.BringUpFailed) as exc:
        logger.warning("task_manager_route_wake_failed", error_type=type(exc).__name__)
        return Resolution(None, WAKE_FAILED)
    info = await session_bring_up.find_live(ops, session_key)
    return Resolution(info, WOKEN) if info is not None else Resolution(None, WAKE_FAILED)


async def asleep_read_keys(ctx: CplugContext) -> Set[str]:
    return {row["session_uuid"] for row in await ctx.sessions.asleep_read() or ()}


class Seen:

    def __init__(self, infos: Sequence[Any], keys: Mapping[str, str], asleep: Optional[Sequence[Mapping[str, Any]]] = None) -> None:
        self.live: Dict[str, Any] = {}
        for info in infos:
            key = keys.get(info.session.id)
            if key:
                self.live.setdefault(key, info)
        self._asleep: Optional[Set[str]] = None if asleep is None else {str(row["session_uuid"]) for row in asleep}

    async def asleep_keys(self, ctx: CplugContext) -> Set[str]:
        if self._asleep is None:
            self._asleep = await asleep_read_keys(ctx)
        return self._asleep


async def _live_info(ctx: CplugContext, session_key: str, seen: Optional[Seen]) -> Optional[Any]:
    return seen.live.get(session_key) if seen is not None else await session_bring_up.find_live(ctx.sessions, session_key)


async def peek(ctx: CplugContext, session_key: str, seen: Optional[Seen] = None) -> Resolution:
    found = await _swarm_agent(ctx, session_key)
    if found is not None:
        agent = found[1]
        info = await _live_info(ctx, agent.session_uuid, seen) if agent.session_uuid else None
        return Resolution(info, LIVE) if info is not None else Resolution(None, ASLEEP)
    if lead.fallback_agent_id(session_key) is not None:
        return Resolution(None, GONE)
    info = await _live_info(ctx, session_key, seen)
    if info is not None:
        return Resolution(info, LIVE)
    asleep = await seen.asleep_keys(ctx) if seen is not None else await asleep_read_keys(ctx)
    return Resolution(None, ASLEEP if session_key in asleep else GONE)


def without_dnd(rows: List[Dict[str, Any]], dnd: Collection[str]) -> List[Dict[str, Any]]:
    return [r for r in rows if r["key"] not in dnd]


def lead_target(store: "TaskManagerStore", rows: List[Dict[str, Any]], list_key: str) -> Optional[str]:
    if not list_key.isdigit():
        return None
    holder = RoleStore(store).seat(list_key).lead_key
    row = next((r for r in rows if holder and r["key"] == holder and not r.get("elsewhere")), None)
    return row["id"] if row is not None else None


def lead_to_wake(store: "TaskManagerStore", rows: List[Dict[str, Any]], list_key: str) -> str:
    if not list_key.isdigit():
        return ""
    holder = RoleStore(store).seat(list_key).lead_key
    return "" if not holder or any(r["key"] == holder for r in rows) else holder


def session_of(row: Mapping[str, Any], lead_key: str, offer_ok: bool) -> str:
    keys = row.keys()
    claimant = row["claimant"] if "claimant" in keys else ""
    owner = row["owner_session_key"] if "owner_session_key" in keys else ""
    return claimant or owner or (lead_key if offer_ok else "")


def session_keys(store: "TaskManagerStore", list_key: str, rows: Sequence[Mapping[str, Any]]) -> Dict[int, str]:
    holder = (RoleStore(store).seat(list_key).lead_key or "") if list_key.isdigit() else ""
    return {r["id"]: session_of(r, holder, bool(holder) and lead.may_offer(r)) for r in rows}

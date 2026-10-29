
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from src.cplugs.huddle import service as task_manager_service
from src.cplugs.huddle.roles import lead, service as roles_service
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.swarm import SwarmError


class LeadRefused(Exception):
    pass


async def set_lead(ctx: CplugContext, list_key: str, session: Optional[str], *, as_agent: bool = False,
                   seat_only: bool = False) -> Dict[str, Any]:
    if as_agent and seat_only:
        raise LeadRefused("seat only leaves the Swarm agent alone, so it cannot also make the session the agent")
    roster = await roles_service.measure(ctx)
    store = RoleStore(task_manager_service.store(ctx))
    has_agent = list_key in roster.project_agents
    if session is None:
        if has_agent and not seat_only:
            raise LeadRefused("this project's lead is its Swarm project agent; pick another session to take over, or turn the agent off")
        if has_agent:
            seat = await asyncio.to_thread(store.set_lead, list_key, roster.project_agents[list_key], lead.BY_AGENT)
        else:
            seat = await asyncio.to_thread(store.set_lead, list_key, "", lead.BY_OWNER)
        return {"list": list_key, "seat": roles_service.seat_view(seat, roster), "agent": False, "dnd_cleared": False}
    if session == roster.inherited_agent(list_key):
        seat = await asyncio.to_thread(store.set_lead, list_key, session, lead.BY_OWNER)
        return {"list": list_key, "seat": roles_service.seat_view(seat, roster), "agent": False, "dnd_cleared": False}
    if session not in roster.live_keys(list_key) | roster.asleep_keys(list_key):
        raise LeadRefused("that is not an agent session of this project (a Swarm agent other than its project agent cannot lead)")
    was_dnd = session in await asyncio.to_thread(store.dnd_keys)
    swarm = task_manager_service.swarm_of(ctx)
    if seat_only:
        seat = await asyncio.to_thread(store.set_lead, list_key, session, lead.BY_PINNED)
    elif swarm is not None and (has_agent or as_agent):
        if roster.project_agents.get(list_key) != session:
            try:
                await swarm.promote_session(session, list_key)
            except SwarmError as exc:
                raise LeadRefused(str(exc)) from exc
        roster = await roles_service.measure(ctx)
        agent_key = roster.project_agents.get(list_key)
        if agent_key is not None:
            await asyncio.to_thread(store.set_lead, list_key, agent_key, lead.BY_AGENT)
        seat = (await asyncio.to_thread(roles_service.evaluate, store, roster))[list_key]
    else:
        seat = await asyncio.to_thread(store.set_lead, list_key, session, lead.BY_OWNER)
    return {"list": list_key, "seat": roles_service.seat_view(seat, roster), "agent": list_key in roster.project_agents, "dnd_cleared": was_dnd}

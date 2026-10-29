
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from src.cplugs.huddle import own_list, service
from src.cplugs.huddle.roles import lead, port as roles_port, service as roles_service
from src.cplugs.huddle.roles.store import LeadCannotDnd, RoleStore, SeatTaken
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError

logger = structlog.get_logger()

ROLES = ("lead", "dnd")
CallerKey = Callable[[], Awaitable[Optional[str]]]


async def role_set(ctx: CplugContext, caller: AgentCaller, args: dict, *, caller_key: CallerKey) -> Dict[str, Any]:
    """Set or clear one role on the CALLING session: ``role`` ``lead`` or ``dnd``, ``on`` true or false.

    Inputs: ctx; caller; args {role, on}; caller_key (reads this pane's stable key).
    Output: {role, on, list?, lead?}: ``list`` and the seat as ``lead`` for the lead role.
    Raises: ToolError (an unknown argument, a bad value, an external token, no project, a Swarm agent, a seat that is held, releasing a
      seat you do not hold, a session list that cannot be read).
    Example: await role_set(ctx, caller, {"role": "dnd", "on": True}, caller_key=key)  # {"role": "dnd", "on": True}
    """
    unknown = sorted(set(args) - {"role", "on"})
    if unknown:
        raise ToolError(f"unknown argument(s): {', '.join(unknown)}")
    role, on = args.get("role"), args.get("on")
    if role not in ROLES or not isinstance(on, bool):
        raise ToolError("role is lead or dnd, and on is true or false")
    if caller.external:
        raise ToolError("roles belong to a session; an external token has none")
    key = await caller_key()
    if key is None:
        raise ToolError("could not tell which session you are")
    store = RoleStore(service.store(ctx))
    if role == "dnd":
        try:
            await roles_service.set_dnd(ctx, store, key, on)
        except LeadCannotDnd as exc:
            raise ToolError("a project lead cannot go on do not disturb: that switch is for the other agents only") from exc
        roles_port.announce(ctx)
        return {"role": role, "on": on}
    return await _set_lead(ctx, caller, store, key, on)


async def _set_lead(ctx: CplugContext, caller: AgentCaller, store: RoleStore, key: str, on: bool) -> Dict[str, Any]:
    project = await own_list.own_project(ctx, caller)
    if project is None:
        raise ToolError("your session belongs to no project, so it has no project to lead")
    try:
        roster = await roles_service.measure(roles_port.session_ctx(ctx))
    except roles_service.RolesUnmeasured as exc:
        raise ToolError(f"could not read the sessions to check the lead seat: {exc}") from exc
    if key not in roster.live_keys(project):
        if await roles_service.is_swarm_body(ctx, caller.current_session_id):
            raise ToolError("a swarm agent cannot be a project lead; only the project's own project agent leads it")
        raise ToolError("only an agent session of this project can lead it")
    if on:
        try:
            seat = await asyncio.to_thread(store.take_if_vacant, project, key, roster.live_keys(project), roster.asleep_keys(project), lead.BY_SESSION,
                                           roster.present_keys(project))
        except SeatTaken as exc:
            name = roster.labels.get(exc.holder, exc.holder)
            raise ToolError(f"{name} leads this project; ask the owner to change it") from exc
    else:
        current = await asyncio.to_thread(store.seat, project)
        if current.lead_key != key:
            raise ToolError("you do not hold this project's lead seat")
        if roster.project_agents.get(project) == key:
            raise ToolError("you are this project's Swarm project agent, so you are its lead; ask the owner to change that")
        seat = await asyncio.to_thread(store.set_lead, project, "", lead.BY_SESSION)
    roles_port.announce(ctx)
    return {"role": "lead", "on": on, "list": project, "lead": roles_service.seat_view(seat, roster)}


async def header(ctx: CplugContext, caller: AgentCaller, list_key: str, caller_key: CallerKey) -> Optional[Dict[str, Any]]:
    """The ``roles`` header of a project list's ``task_manager_tasks_list`` answer: who leads it and what this session is. None when it cannot be told.

    Inputs: ctx; caller; list_key; caller_key. Output: {lead: {session, name} | None, you: {lead, dnd}} or None (not a project's list,
      an external token, or the sessions could not be read: a header is never worth failing a read for).
    """
    if not list_key.isdigit() or caller.external:
        return None
    try:
        roster = await roles_service.measure(roles_port.session_ctx(ctx))
        store = RoleStore(service.store(ctx))
        seats = await asyncio.to_thread(roles_service.evaluate, store, roster)
        me = await caller_key()
        dnd = await asyncio.to_thread(store.dnd_keys)
    except (roles_service.RolesUnmeasured, AttributeError, TypeError, LookupError, OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_roles_header_skipped", list=list_key, error_type=type(exc).__name__)
        return None
    holder, _reason = roles_service.holder_of(seats.get(list_key, lead.Seat(list_key)), roster)
    return {"lead": {"session": holder, "name": roster.labels.get(holder)} if holder else None,
            "you": {"lead": holder is not None and holder == me, "dnd": me in dnd}}


from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, StrictBool

from src.cplugs.huddle import service
from src.cplugs.huddle.roles import tags
from src.cplugs.huddle.roles import port as roles_port, retrofit, service as roles_service, set_lead
from src.cplugs.huddle.roles.store import LeadCannotDnd, RoleStore
from src.cplugs.huddle.routes import Ctx, known_list, router, run_store
from src.cplugs.huddle.routes_nudge import SESSION_KEY
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.swarm import SwarmError


class LeadRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    session: Optional[str]
    agent: StrictBool = False
    seat_only: StrictBool = False


class DndRequest(BaseModel):
    """One session's do-not-disturb switch. ``dnd`` is required, a real boolean."""

    model_config = ConfigDict(extra="forbid")
    dnd: StrictBool


class RetrofitRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    skip: List[str] = []
    picks: Dict[str, str] = {}
    dry_run: StrictBool = True


class TagRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")
    session: Optional[str]


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "task_manager_invalid", "detail": detail})


async def read_roles(ctx: CplugContext) -> Dict[str, Any]:
    try:
        roster = await roles_service.measure(ctx)
    except roles_service.RolesUnmeasured as exc:
        raise HTTPException(status_code=503, detail={"code": "task_manager_roles_unmeasured", "detail": str(exc)}) from exc
    store = RoleStore(service.store(ctx))
    seats = await run_store(lambda: roles_service.evaluate(store, roster))
    return {"leads": {key: roles_service.seat_view(seat, roster) for key, seat in seats.items() if seat.ever_led},
            "dnd": sorted(await run_store(store.dnd_keys))}


@router.get("/roles")
async def get_roles(ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Every project's lead seat and every do-not-disturb session. Output: {leads: {list key: seat}, dnd: [session key]}."""
    return await read_roles(ctx)


@router.put("/lists/{key}/lead")
async def put_lead(key: str, body: LeadRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """
    Raises: 400 ``task_manager_invalid`` (not a project's list, a bad key, a session that is not an agent session of this project, a promotion
      the Swarm refused, clearing a project that has a Swarm project agent, or ``agent`` with ``seat_only``), 404 (unknown list), 503 (sessions unreadable).
    """
    key, _name = await known_list(ctx, key)
    if not key.isdigit():
        raise _invalid("a lead belongs to a project's list, not the shared list or an agent thread")
    if body.session is not None and not SESSION_KEY.match(body.session):
        raise _invalid("the session key is its stable session_uuid")
    try:
        answer = await set_lead.set_lead(ctx, key, body.session, as_agent=body.agent, seat_only=body.seat_only)
    except roles_service.RolesUnmeasured as exc:
        raise HTTPException(status_code=503, detail={"code": "task_manager_roles_unmeasured", "detail": str(exc)}) from exc
    except set_lead.LeadRefused as exc:
        raise _invalid(str(exc)) from exc
    roles_port.announce(ctx)
    return answer


@router.put("/sessions/{session_uuid}/dnd")
async def put_dnd(session_uuid: str, body: DndRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Switch one session's do not disturb. Output: {session, dnd}. Raises: 400 ``task_manager_invalid`` for a key that is not a bounded id, or for a project lead."""
    if not SESSION_KEY.match(session_uuid):
        raise _invalid("the session key is its stable session_uuid")
    try:
        stored = await roles_service.set_dnd(ctx, RoleStore(service.store(ctx)), session_uuid, body.dnd)
    except LeadCannotDnd as exc:
        raise _invalid("a project lead cannot go on do not disturb: that switch is for the other agents only") from exc
    roles_port.announce(ctx)
    return {"session": session_uuid, "dnd": stored}


@router.put("/items/{item_id}/tag")
async def put_tag(item_id: int, body: TagRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Tag a task to an agent session, or clear the tag (null). Output: the item. Raises: 400 ``task_manager_invalid``, 404 (unknown item)."""
    store = service.store(ctx)
    try:
        key = await tags.target_key(ctx, store, body.session or "", caller_key=None)
    except tags.TagRefused as exc:
        raise _invalid(str(exc)) from exc
    return await run_store(lambda: tags.set_tag(store, item_id, key))


@router.get("/leads/retrofit")
async def get_retrofit_plan(skip: List[str] = Query(default=[]), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The retrofit plan, one row per live project; nothing changes. Output: {dry_run: true, plan, promoted: 0, cleared: 0, refused: 0}. Raises: 503 (sessions unreadable)."""
    try:
        return await retrofit.run(ctx, skip, None, dry_run=True)
    except roles_service.RolesUnmeasured as exc:
        raise HTTPException(status_code=503, detail={"code": "task_manager_roles_unmeasured", "detail": str(exc)}) from exc


@router.post("/leads/retrofit")
async def post_retrofit(body: RetrofitRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Run the retrofit (``dry_run`` true, the default, only plans). Output: {dry_run, plan, promoted, cleared, refused}. Raises: 400 (the Swarm is unavailable), 503."""
    try:
        done = await retrofit.run(ctx, body.skip, body.picks, dry_run=body.dry_run)
    except roles_service.RolesUnmeasured as exc:
        raise HTTPException(status_code=503, detail={"code": "task_manager_roles_unmeasured", "detail": str(exc)}) from exc
    except SwarmError as exc:
        raise _invalid(str(exc)) from exc
    if not body.dry_run:
        roles_port.announce(ctx)
    return done

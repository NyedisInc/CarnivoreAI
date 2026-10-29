
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool

from src.cplugs.huddle import service
from src.cplugs.huddle.nudge_store import NudgeStore
from src.cplugs.huddle.roles.service import notify_prefs
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.huddle.routes import Ctx, known_list, router, run_store
from src.cplugs.sdk import CplugContext


SESSION_KEY = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class SessionPrefsRequest(BaseModel):
    """One session's own switch. ``nudge`` is required: true, false, or null to follow the project; a missing key is not a silent clear."""

    model_config = ConfigDict(extra="forbid")
    nudge: Optional[StrictBool]


class ListPrefsRequest(BaseModel):
    """A project's huddle switches. ``nudge`` is required: a missing key is not a silent off."""

    model_config = ConfigDict(extra="forbid")
    nudge: StrictBool


async def _project_key(ctx: CplugContext, key: str) -> str:
    key, _name = await known_list(ctx, key)
    if not key.isdigit():
        raise HTTPException(status_code=400, detail={
            "code": "task_manager_invalid", "detail": "the nudge belongs to a project's list, not the shared list or an agent thread"})
    return key


@router.get("/lists/{key}/prefs")
async def get_list_prefs(key: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """A list's huddle switches: a project is ON unless switched off, ``all`` and an agent thread read off. Output: {list, nudge}."""
    key, _name = await known_list(ctx, key)
    prefs = await run_store(NudgeStore(service.store(ctx)).prefs)
    return {"list": key, "nudge": prefs.get(key, key.isdigit())}


@router.put("/lists/{key}/prefs")
async def put_list_prefs(key: str, body: ListPrefsRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Switch a project's nudge on or off. The list's topic is notified (every window re-reads) and the scheduler re-armed. Output: {list, nudge}."""
    key = await _project_key(ctx, key)
    await run_store(lambda: NudgeStore(service.store(ctx)).set_pref(key, body.nudge))
    notify_prefs(ctx)
    return {"list": key, "nudge": body.nudge}


def _session_key(session_uuid: str) -> str:
    if not SESSION_KEY.match(session_uuid):
        raise HTTPException(status_code=400, detail={"code": "task_manager_invalid", "detail": "the session key is its stable session_uuid"})
    return session_uuid


@router.get("/session-prefs")
async def get_all_prefs(ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Every set session switch, project switch, project lead and do-not-disturb session. Output: {sessions: {uuid: bool}, lists: {key: bool}, leads: {key: uuid}, dnd: [uuid]}."""
    store = NudgeStore(service.store(ctx))
    roles = RoleStore(service.store(ctx))
    seats = await run_store(roles.seats)
    return {"sessions": await run_store(store.session_prefs), "lists": await run_store(store.prefs),
            "leads": {key: seat.lead_key for key, seat in seats.items() if seat.lead_key}, "dnd": sorted(await run_store(roles.dnd_keys))}


@router.get("/sessions/{session_uuid}/prefs")
async def get_session_prefs(session_uuid: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """One session's own nudge switch (null when unset or unknown: a read never refuses a key). Output: {session, nudge}."""
    prefs = await run_store(NudgeStore(service.store(ctx)).session_prefs)
    return {"session": session_uuid, "nudge": prefs.get(session_uuid)}


@router.put("/sessions/{session_uuid}/prefs")
async def put_session_prefs(session_uuid: str, body: SessionPrefsRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Set (true or false) or clear (null) one session's own nudge switch; the scheduler is re-armed. Output: {session, nudge}."""
    key = _session_key(session_uuid)
    stored = await run_store(lambda: NudgeStore(service.store(ctx)).set_session_pref(key, body.nudge))
    notify_prefs(ctx)
    return {"session": key, "nudge": stored}


from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from src.cplugs.huddle import client_writes, inbox, inbox_filing, inbox_renudge, send_queue, service
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.routes import Ctx, known_list, mapped_errors, router, run_store
from src.cplugs.huddle.rules import JOE
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()


class AddBoxRequest(BaseModel):
    """The add box's text, kept exactly as typed (trimmed at the ends)."""

    model_config = ConfigDict(extra="forbid")
    text: str
    client_id: Optional[str] = None
    retry_age_s: Optional[float] = Field(None, ge=0, le=client_writes.MAX_RETRY_AGE_S)


class FileRequest(BaseModel):
    """The items an entry is filed as (validated whole by ``inbox_filing.parse_specs``)."""

    model_config = ConfigDict(extra="forbid")
    items: List[Dict[str, Any]]


class InboxPrefsRequest(BaseModel):
    """A project's inbox switch. Required: a missing key is not a silent off."""

    model_config = ConfigDict(extra="forbid")
    file_through_session: StrictBool


async def _project_key(ctx: CplugContext, key: str) -> str:
    key, _name = await known_list(ctx, key)
    if not key.isdigit():
        raise HTTPException(status_code=400, detail={
            "code": "task_manager_invalid", "detail": "the inbox belongs to a project's list, not the shared list or an agent thread"})
    return key


async def _renudge_stuck(inboxes: InboxStore, key: str) -> None:
    try:
        await run_store(lambda: inbox_renudge.rearm_stuck(inboxes, key, inboxes._store._clock()))
    except HTTPException as exc:
        logger.warning("task_manager_inbox_renudge_failed", list=key, status=exc.status_code)


@router.post("/lists/{key}/inbox")
async def add_box(key: str, body: AddBoxRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    key, _name = await known_list(ctx, key)
    store = service.store(ctx)
    inboxes = InboxStore(store)

    async def write() -> Dict[str, Any]:
        if key.isdigit() and await run_store(lambda: inboxes.pref(key)):
            entry = await run_store(lambda: inboxes.add(key, body.text))
            await _renudge_stuck(inboxes, key)
            send_queue.queue_change(ctx, key)
            return {"queued": True, "entry": entry, "item": None}
        return {"queued": False, "entry": None, "item": await run_store(lambda: store.add(key, body.text, actor=JOE))}

    async def recover(since: float) -> Optional[Dict[str, Any]]:
        return await run_store(lambda: client_writes.find_inbox(store, key, body.text, since) or client_writes.find_added(store, key, body.text, since))

    async def replay(ref: Dict[str, Any]) -> Dict[str, Any]:
        return await run_store(lambda: client_writes.replay_add(store, ref))

    with mapped_errors():
        return await client_writes.once(f"add:{key}", client_writes.check_id(body.client_id), body.retry_age_s,
                                        run=write, recover=recover, ref_of=client_writes.add_ref, replay=replay)


@router.get("/inbox")
async def list_inbox(list: Optional[str] = Query(None), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The open entries, oldest first. Output: {entries: [entry]}."""
    return {"entries": await run_store(lambda: InboxStore(service.store(ctx)).open_entries(list))}


@router.get("/inbox/{entry_id}")
async def get_entry(entry_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """One entry in full. Output: the entry (raw text, status, the item ids it was filed as)."""
    return await run_store(lambda: InboxStore(service.store(ctx)).get(entry_id))


@router.post("/inbox/{entry_id}/nudge")
async def nudge_entry(entry_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Re-send one stuck add box entry right now. Output: {entry, sent} (``sent``: a session was told)."""
    store = service.store(ctx)
    with mapped_errors():
        return await inbox_renudge.nudge_entry(ctx, run_store, InboxStore(store), entry_id, store._clock())


@router.post("/inbox/{entry_id}/file")
async def file_entry(entry_id: int, body: FileRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    specs = await run_store(lambda: inbox_filing.parse_specs(body.items, allowed_states=inbox_filing.OWNER_STATES))
    return await run_store(lambda: inbox_filing.file_as_owner(ctx, entry_id, specs))


@router.get("/lists/{key}/inbox-prefs")
async def get_inbox_prefs(key: str, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """A list's inbox switch (``all`` and an agent thread read off). Output: {list, file_through_session}."""
    key, _name = await known_list(ctx, key)
    return {"list": key, "file_through_session": key.isdigit() and await run_store(lambda: InboxStore(service.store(ctx)).pref(key))}


@router.put("/lists/{key}/inbox-prefs")
async def put_inbox_prefs(key: str, body: InboxPrefsRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Switch a project's inbox on or off; the list's topic is notified. Output: {list, file_through_session}."""
    key = await _project_key(ctx, key)
    await run_store(lambda: InboxStore(service.store(ctx)).set_pref(key, body.file_through_session))
    return {"list": key, "file_through_session": body.file_through_session}

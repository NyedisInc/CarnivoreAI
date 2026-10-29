
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.cplugs.sdk import session_bring_up
from src.cplugs.huddle import held, service, send_wake, sending
from src.cplugs.huddle.roles import tag_send
from src.cplugs.huddle.rules import ALL_LIST
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

LEAD = "a scheduled swarm came due"
QUOTE_CHARS = 80


class FireFailed(Exception):
    """A due todo could not be delivered; the message is the sentence the row shows."""


async def _run(call: Callable[[], Any]) -> Any:
    return await asyncio.to_thread(call)


def lead_line(item: Dict[str, Any]) -> str:
    words = (item.get("title") or item.get("text") or "").strip().replace("\n", " ")
    quoted = words if len(words) <= QUOTE_CHARS else words[:QUOTE_CHARS - 1].rstrip() + "..."
    return f'{LEAD}: item {item["id"]}, "{quoted}". '


async def bring_up(ctx: CplugContext, list_key: str) -> str:
    if list_key == ALL_LIST:
        raise FireFailed("the shared list has no running agent session to send to, and no project to start one in")
    try:
        ready = await session_bring_up.wake_newest_or_start(ctx.sessions, int(list_key))
    except session_bring_up.RestoreOfferOpen:
        raise
    except session_bring_up.BringUpFailed as exc:
        cause = exc.__cause__
        if isinstance(cause, HTTPException):
            raise FireFailed(f"could not start a session: {held.refusal_reason(cause)}") from cause
        raise FireFailed(str(exc)) from exc
    logger.info("task_manager_scheduled_brought_up", list=list_key, session_id=ready)
    return ready


def pick_target(ctx: CplugContext, rows: List[dict], list_key: str) -> Optional[str]:
    own = [r for r in rows if not r.get("elsewhere")]
    if not own:
        return None
    choice = service.send_choice(ctx, rows, list_key)
    return choice["default"] or own[0]["id"]


def hold_for_offer(ctx: CplugContext, item: Dict[str, Any]) -> str:
    key = item["list"]
    busy = HTTPException(status_code=409, detail={"code": session_bring_up.RestoreOfferOpen.code,
                                                   "detail": "a reopen offer lists a session of this project"})

    async def retry() -> Any:
        if int(key) in session_bring_up.offer_holds_projects():
            raise busy
        return await deliver(ctx, item)

    held.hold(ctx, key, "", None, busy, retry)
    logger.info("task_manager_scheduled_held_for_offer", item=item["id"], list=key)
    return sending.HELD


async def deliver(ctx: CplugContext, item: Dict[str, Any]) -> str:
    key = item["list"]
    name = (await _run(lambda: service.project_names(ctx))).get(key)
    rows = await service.candidate_rows(ctx, key)
    target, extra = await tag_send.item_target(ctx, _run, key, item["id"], rows)
    if target is None:
        rows = await send_wake.rows_with_lead(ctx, _run, key, rows) if key.isdigit() else rows
        target = await _run(lambda: pick_target(ctx, rows, key))
    rows = rows + extra
    if target is None:
        try:
            target = await bring_up(ctx, key)
        except session_bring_up.RestoreOfferOpen:
            return hold_for_offer(ctx, item)
        rows = await service.candidate_rows(ctx, key)
    reason = "scheduled"
    try:
        await sending.paste_send(ctx, _run, key, name, rows, target, reason, aggregate=False, lead=lead_line(item))
    except HTTPException as exc:
        outcome = sending.held_or_refused(ctx, _run, key, name, rows, target, reason, exc, lead=lead_line(item))
        if outcome["status"] != sending.HELD:
            raise FireFailed(f"not sent: {outcome['reason']}") from exc
        return sending.HELD
    held.clear(ctx, key)
    logger.info("task_manager_scheduled_told", item=item["id"], list=key, target=target)
    return sending.SENT


from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import structlog

from src.cplugs.huddle import blockers, service, wait_copy, wait_runner, waits
from src.cplugs.huddle.rules import CARNIVORE_KEY, OWNER_KEY, TaskManagerForbidden, TaskManagerInvalid
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

CLEARED, FAILED = "cleared", "failed"
RESULTS = (CLEARED, FAILED)
MAX_REASON = 300
REFUSED = "no live wait on this task accepts that: the token is wrong, was already used, or the wait has ended"


async def resolve(ctx: CplugContext, item_id: int, result: str, reason: Optional[str] = None, *, token: Optional[str] = None,
                  authed: bool = False, by_agent: bool = False, by: str = "") -> Dict[str, Any]:
    if result not in RESULTS:
        raise TaskManagerInvalid(f"result must be one of {', '.join(RESULTS)}")
    reason = (reason or "").strip()
    if len(reason) > MAX_REASON:
        raise TaskManagerInvalid(f"reason is at most {MAX_REASON} characters")
    store = waits.WaitStore(service.store(ctx))
    wait = await asyncio.to_thread(store.for_item if authed else (lambda i: store.verify(i, token)), item_id)
    if wait is None and authed:
        return await _clear_hold(ctx, item_id, result, reason, by_agent=by_agent, by=by)
    if wait is None:
        logger.debug("task_manager_wait_callback_refused", item=item_id, authed=authed)
        raise TaskManagerForbidden(REFUSED)
    if by_agent and wait["status"] == waits.ESCALATED:
        raise TaskManagerForbidden("the owner has been asked about this wait (push, drop or wait longer); he answers it, an agent cannot end it")
    if result == CLEARED:
        status, text, detail = waits.CLEARED, wait_copy.cleared(reason or wait["waiting_on"] or "the wait"), wait_runner.CLEARED_DETAIL
    else:
        status, text, detail = waits.FAILED, wait_copy.failed(reason), wait_runner.FAILED_DETAIL
    item = await wait_runner.finish(ctx, wait, status, text, detail)
    if item is None:
        raise TaskManagerForbidden(REFUSED)
    logger.info("task_manager_wait_callback", item=item_id, result=result, authed=authed)
    return {"ok": True, "item_id": item_id, "result": result, "state": item["state"]}


async def _clear_hold(ctx: CplugContext, item_id: int, result: str, reason: str, *, by_agent: bool, by: str) -> Dict[str, Any]:
    if result == CLEARED:
        text, detail = wait_copy.cleared(reason or blockers.HOLD_TEXT), wait_runner.CLEARED_DETAIL
    else:
        text, detail = wait_copy.failed(reason), wait_runner.FAILED_DETAIL
    who = (by or CARNIVORE_KEY) if by_agent else OWNER_KEY
    item = await wait_runner.finish_hold(ctx, item_id, who, text, detail, tell=not by_agent)
    if item is None:
        logger.debug("task_manager_wait_callback_refused", item=item_id, authed=True)
        raise TaskManagerForbidden(REFUSED)
    logger.info("task_manager_hold_resolved", item=item_id, result=result, by_agent=by_agent)
    return {"ok": True, "item_id": item_id, "result": result, "state": item["state"]}

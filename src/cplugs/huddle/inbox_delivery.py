
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import held, inbox, inbox_stuck, inbox_target, service, send_queue, sending
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.rules import TaskManagerError
from src.cplugs.huddle.roles import route
from src.cplugs.sdk import CplugContext, session_bring_up

logger = structlog.get_logger()

REASON = "inbox"


async def _run(call: Callable[[], Any]) -> Any:
    return await asyncio.to_thread(call)


async def _own_rows(ctx: CplugContext, key: str) -> List[dict]:
    return [r for r in await service.candidate_rows(ctx, key) if not r.get("elsewhere")]


async def _rows_or_wake(ctx: CplugContext, key: str) -> List[dict]:
    rows = await _own_rows(ctx, key)
    if rows:
        return rows
    try:
        woken = await session_bring_up.wake_newest(ctx.sessions, int(key))
    except session_bring_up.BringUpFailed as exc:
        logger.info("task_manager_inbox_wake_failed", list=key, error=str(exc)[:200])
        return []
    return await _own_rows(ctx, key) if woken is not None else []


async def _wake_lead(ctx: CplugContext, key: str, rows: List[dict]) -> List[dict]:
    holder = await _run(lambda: inbox_target.lead_wake_key(ctx, rows, key))
    found = await route.resolve(ctx, holder) if holder else None
    return await _own_rows(ctx, key) if found is not None and found.ready else rows


async def deliver_one(ctx: CplugContext, store: InboxStore, entry: Dict[str, Any], now: float, prefer: Optional[str] = None) -> bool:
    key = entry["list"]
    if not key.isdigit() or held.is_held(key):
        return False
    rows = await _rows_or_wake(ctx, key)
    if await _run(lambda: inbox_target.lead_wake_key(ctx, rows, key)):
        rows = await _wake_lead(ctx, key, rows)
    if not rows:
        return False
    target = prefer if prefer and any(r["id"] == prefer for r in rows) else await _run(lambda: inbox_target.choose(ctx, rows, key))
    if target is None:
        return False
    name = (await _run(lambda: service.project_names(ctx))).get(key)
    await send_queue.before_immediate(ctx, key, target)
    try:
        await sending.paste_send(ctx, _run, key, name, rows, target, REASON, aggregate=False, lead=inbox.lead_line(entry["id"], entry["text"]))
    except HTTPException as exc:
        logger.info("task_manager_inbox_not_sent", list=key, entry=entry["id"], target=target, code=held.refusal_code(exc))
        return False
    await _run(lambda: store.mark_delivered(entry["id"], target, now))
    logger.info("task_manager_inbox_told", list=key, entry=entry["id"], target=target)
    return True


async def deliver_pass(ctx: CplugContext, clock: Callable[[], float] = time.time) -> int:
    store = InboxStore(service.store(ctx))
    wait_s = inbox.clamp_fallback(ctx.settings_now().get(inbox.FALLBACK_SETTING))
    acted = 0
    for entry in await _run(store.active_entries):
        now = clock()
        if send_queue.is_queued(entry["list"]):
            continue
        try:
            if inbox.expired(entry, now, wait_s):
                if await _run(lambda: inbox_stuck.raise_question(store, entry, wait_s)) is not None:
                    acted += 1
            elif entry["status"] == inbox.QUEUED and await deliver_one(ctx, store, entry, now):
                acted += 1
        except TaskManagerError as exc:
            logger.info("task_manager_inbox_skipped", entry=entry["id"], reason=str(exc))
        except (OSError, RuntimeError, ValueError, LookupError, AttributeError, sqlite3.Error) as exc:
            logger.error("task_manager_inbox_entry_failed", entry=entry["id"], error_type=type(exc).__name__, error=str(exc)[:200])
    return acted

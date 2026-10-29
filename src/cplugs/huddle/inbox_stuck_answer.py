
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from src.cplugs.huddle import inbox, inbox_delivery, service
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.roles import ask
from src.cplugs.sdk import CplugContext, session_bring_up

logger = structlog.get_logger()

Runner = Callable[[Callable[[], Any]], Awaitable[Any]]


async def after_answer(ctx: CplugContext, run: Runner, posted: Dict[str, Any]) -> Optional[str]:
    outcome = posted.get("carnivore")
    if not outcome or outcome["category"] != ask.INBOX_STUCK:
        return None
    entry_id = (posted["item"].get("from_inbox") or {}).get("id")
    if entry_id is None:
        logger.warning("task_manager_inbox_stuck_answer_orphaned", item=posted["item"]["id"])
        return None
    inboxes = InboxStore(service.store(ctx))
    choice, now = outcome["choice"], service.store(ctx)._clock()
    entry = await run(lambda: inboxes.get(entry_id))
    if entry["status"] != inbox.STUCK:
        await run(lambda: inboxes.retire_questions(entry_id))
        return None
    if choice == ask.FILE_MYSELF:
        await run(lambda: inboxes.file_plain(entry_id, now, inbox.REASON_OWNER_FILED))
    else:
        await run(lambda: inboxes.rearm(entry_id, now))
        if choice == ask.START_SESSION:
            await _start_and_offer(ctx, run, inboxes, entry_id, now)
    await run(lambda: inboxes.retire_questions(entry_id))
    logger.info("task_manager_inbox_stuck_answered", entry=entry_id, choice=choice)
    return choice


async def _start_and_offer(ctx: CplugContext, run: Runner, inboxes: InboxStore, entry_id: int, now: float) -> None:
    entry = await run(lambda: inboxes.get(entry_id))
    if not entry["list"].isdigit():
        return
    try:
        started = await session_bring_up.wake_newest_or_start(ctx.sessions, int(entry["list"]))
    except session_bring_up.BringUpFailed as exc:
        logger.warning("task_manager_inbox_start_failed", entry=entry_id, list=entry["list"], error=str(exc)[:200])
        return
    await inbox_delivery.deliver_one(ctx, inboxes, entry, now, prefer=started)

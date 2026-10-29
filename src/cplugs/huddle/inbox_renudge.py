
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List

import structlog

from src.cplugs.huddle import inbox, inbox_delivery
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

Runner = Callable[[Callable[[], Any]], Awaitable[Any]]


def rearm_stuck(inboxes: InboxStore, list_key: str, now: float) -> List[int]:
    again: List[int] = []
    for entry in inboxes.open_entries(list_key):
        if entry["status"] == inbox.STUCK and inboxes.rearm(entry["id"], now):
            inboxes.retire_questions(entry["id"])
            again.append(entry["id"])
    if again:
        logger.info("task_manager_inbox_renudged_on_send", list=list_key, entries=again)
    return again


async def nudge_entry(ctx: CplugContext, run: Runner, inboxes: InboxStore, entry_id: int, now: float) -> Dict[str, Any]:
    await run(lambda: inboxes.adopt_promoted(entry_id, now))
    entry = await run(lambda: inboxes.get(entry_id))
    if entry["status"] != inbox.STUCK:
        raise TaskManagerInvalid(f"inbox entry {entry_id} is {entry['status']}, not stuck: only an entry nobody filed can be nudged")
    if await run(lambda: inboxes.rearm(entry_id, now)):
        await run(lambda: inboxes.retire_questions(entry_id))
    entry = await run(lambda: inboxes.get(entry_id))
    sent = entry["status"] == inbox.QUEUED and await inbox_delivery.deliver_one(ctx, inboxes, entry, now)
    logger.info("task_manager_inbox_nudged", entry=entry_id, sent=sent)
    return {"entry": await run(lambda: inboxes.get(entry_id)), "sent": sent}

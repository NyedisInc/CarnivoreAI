
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Callable, List, Optional, Set

import structlog

from src.cplugs.huddle import kinds, lineage, reply_return, rules, service
from src.cplugs.huddle.rules import TaskManagerError
from src.cplugs.sdk import CplugContext, turn_events

logger = structlog.get_logger()

RESTING = ("idle", "finished_unread", "question", "notice")
SETTLE_ERRORS = (OSError, sqlite3.Error, TaskManagerError, RuntimeError, LookupError)

_unsubscribe: Optional[Callable[[], None]] = None
_pending: "Set[asyncio.Task[None]]" = set()


def settle(store: Any, session_key: str) -> List[int]:
    with closing(store._read_connection()) as conn:
        found = reply_return.unanswered_ids(conn, session_key)
    returned: List[int] = []
    for item_id, origin in found:
        try:
            store.update(item_id, actor=rules.CLAUDE, state=origin, decided=lineage.Decided(lineage.CARNIVORE, reply_return.NOT_ANSWERED))
            store.post(item_id, reply_return.NOT_ANSWERED_TEXT.format(state=origin), actor=rules.CLAUDE, kind=kinds.INFO, author_key=rules.CARNIVORE_KEY)
        except TaskManagerError as exc:
            logger.info("task_manager_turn_return_skipped", item=item_id, error=str(exc)[:200])
            continue
        logger.info("task_manager_turn_return", item=item_id, back_to=origin, session_key=session_key)
        returned.append(item_id)
    return returned


async def on_turn_end(ctx: CplugContext, session_id: Optional[str]) -> List[int]:
    if not session_id:
        return []
    try:
        infos = await ctx.sessions.list()
        info = next((i for i in infos if i.session.id == session_id), None)
        if info is None or info.activity_status not in RESTING:
            return []
        key = (await ctx.sessions.durable_keys([info])).get(session_id)
        if not key:
            return []
        return await asyncio.to_thread(settle, service.store(ctx), key)
    except SETTLE_ERRORS as exc:
        logger.warning("task_manager_turn_return_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        return []


def start(ctx: CplugContext) -> None:
    global _unsubscribe
    stop()
    loop = asyncio.get_running_loop()

    def listener(session_id: Optional[str]) -> None:
        def spawn() -> None:
            task = loop.create_task(on_turn_end(ctx, session_id), name="huddle-turn-return")
            _pending.add(task)
            task.add_done_callback(_pending.discard)

        loop.call_soon_threadsafe(spawn)

    _unsubscribe = turn_events.subscribe(listener)


def stop() -> None:
    global _unsubscribe
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None

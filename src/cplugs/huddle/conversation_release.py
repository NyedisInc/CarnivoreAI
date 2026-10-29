
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Callable, Optional, Set

import structlog

from src.cplugs.huddle import service
from src.cplugs.sdk import conversation_events

logger = structlog.get_logger()

_unsubscribe: Optional[Callable[[], None]] = None
_pending: "Set[asyncio.Task[None]]" = set()


async def release(ctx: Any, session_key: str) -> list:
    try:
        released = await asyncio.to_thread(service.store(ctx).release_conversation_claims, session_key)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_conversation_release_failed", error_type=type(exc).__name__, error=str(exc))
        return []
    if released:
        logger.info("task_manager_claims_released_conversation_changed", session_key=session_key, lists=released)
    return released


def start(ctx: Any) -> None:
    global _unsubscribe
    stop()
    loop = asyncio.get_running_loop()

    def on_changed(session_key: str) -> None:
        def spawn() -> None:
            task = loop.create_task(release(ctx, session_key), name="huddle-conversation-release")
            _pending.add(task)
            task.add_done_callback(_pending.discard)

        loop.call_soon_threadsafe(spawn)

    _unsubscribe = conversation_events.subscribe(on_changed)


def stop() -> None:
    global _unsubscribe
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None

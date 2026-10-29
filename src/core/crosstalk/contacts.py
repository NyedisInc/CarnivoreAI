
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any

import structlog

from src.core.crosstalk import directory, store
from src.core.mcp.protocol import BatchView

logger = structlog.get_logger()
_last_input: dict[str, float] = {}


async def _propagate_owner_window(app: Any, card: dict, updates: list) -> None:
    try:
        from src.core.crosstalk.delivery import peer
        await peer.propagate_owner_window(app, card, updates)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        logger.warning('crosstalk_owner_input_peer_update_failed', error_type=type(exc).__name__)


def grant_contact(sender_key: str, receiver_key: str, sender_epoch: int | None,
                  receiver_epoch: int | None, *, source: str = 'spawn') -> None:
    store.grant_contact(sender_key, receiver_key, sender_epoch, receiver_epoch, source=source)


_in_flight: set[str] = set()
_tasks: set[asyncio.Task] = set()


async def owner_input(app: Any, session_id: str) -> None:
    now = time.monotonic()
    if now - _last_input.get(session_id, 0) < 1.0:
        return
    _last_input[session_id] = now
    try:
        card = await directory.local_identity(app.state.session_manager, session_id)
        if card:
            updates = await asyncio.to_thread(store.owner_input, str(card.get('session_uuid') or card['id']))
            if updates:
                asyncio.create_task(_propagate_owner_window(app, card, updates))
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        logger.warning('crosstalk_owner_input_record_failed', error_type=type(exc).__name__)


def schedule_owner_input(app: Any, session_id: str) -> bool:
    """Fire ``owner_input`` in the background so a keystroke never waits on it; one run per pane at a time.

    Inputs: app (FastAPI app); session_id (str). Output: bool - True when a task was started, False when one is
    already running for this pane (the keystroke is coalesced into it). Any failure is logged, never swallowed.
    """
    if session_id in _in_flight:
        return False
    _in_flight.add(session_id)
    task = asyncio.get_running_loop().create_task(owner_input(app, session_id))
    _tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _in_flight.discard(session_id)
        _tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error('crosstalk_owner_input_task_failed', error_type=type(t.exception()).__name__,
                         session_id=session_id)

    task.add_done_callback(_done)
    return True

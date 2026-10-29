
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Hashable, Mapping, Optional

import structlog

from src.api.resize_negotiation import (
    apply_effective_size,
    broadcast_size,
    get_negotiator,
    release_client_resize,
)
from src.core.terminal_size import TerminalSizeNegotiator
from src.models import WSMessageType

logger = structlog.get_logger()

CLIENT_ID_QUERY_PARAM = "client_id"

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

GRACE_SECONDS = 20.0


def valid_client_id(value: Any) -> bool:
    return isinstance(value, str) and bool(CLIENT_ID_PATTERN.match(value))


def client_id_from_query(query: Mapping[str, str]) -> Optional[str]:
    value = query.get(CLIENT_ID_QUERY_PARAM)
    return value if valid_client_id(value) else None


def state(session_id: str, negotiator: TerminalSizeNegotiator) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "master": negotiator.master(session_id),
        "master_attached": negotiator.master_attached(session_id),
    }


def _frame(session_id: str, negotiator: TerminalSizeNegotiator) -> str:
    return json.dumps({"type": WSMessageType.SIZE_MASTER, **state(session_id, negotiator)})


async def attach(websocket: Any, session_manager: Any, session_id: Optional[str]) -> None:
    if not session_id:
        return
    negotiator = get_negotiator(session_manager)
    negotiator.bind_client_id(
        session_id, websocket, client_id_from_query(websocket.query_params))
    await websocket.send_text(_frame(session_id, negotiator))


async def release_client(
    session_manager: Any,
    session_id: Optional[str],
    client_key: Hashable,
    connection_manager: Any,
) -> None:
    await release_client_resize(session_manager, session_id, client_key, connection_manager)
    if session_id:
        _arm_grace(session_manager, session_id, connection_manager)


async def set_master(
    session_manager: Any,
    session_id: str,
    client_id: Optional[str],
    connection_manager: Any,
    reason: str,
) -> Dict[str, Any]:
    negotiator = get_negotiator(session_manager)
    effective = negotiator.set_master(session_id, client_id)
    if effective is None:
        await broadcast_size(session_id, negotiator, connection_manager, departed=True)
    else:
        await apply_effective_size(
            session_manager, session_id, negotiator, effective, connection_manager)
    await connection_manager.broadcast_to_session(session_id, _frame(session_id, negotiator))
    _cancel_grace(session_manager, session_id)
    _arm_grace(session_manager, session_id, connection_manager)
    logger.info(
        "size_master_changed",
        session_id=session_id,
        master_set=client_id is not None,
        reason=reason,
        resized=effective is not None,
    )
    return state(session_id, negotiator)


def _grace_tasks(session_manager: Any) -> Dict[str, "asyncio.Task[None]"]:
    tasks = getattr(session_manager, "_size_master_grace", None)
    if tasks is None:
        tasks = {}
        try:
            session_manager._size_master_grace = tasks
        except (AttributeError, TypeError):
            logger.debug("size_master_grace_cache_unavailable")
    return tasks


def _cancel_grace(session_manager: Any, session_id: str) -> None:
    task = _grace_tasks(session_manager).pop(session_id, None)
    if task is not None and not task.done():
        task.cancel()


def _arm_grace(session_manager: Any, session_id: str, connection_manager: Any) -> None:
    negotiator = get_negotiator(session_manager)
    master = negotiator.master(session_id)
    if master is None or negotiator.master_attached(session_id):
        return
    _cancel_grace(session_manager, session_id)
    _grace_tasks(session_manager)[session_id] = asyncio.create_task(
        _expire(session_manager, session_id, master, connection_manager))


async def _expire(
    session_manager: Any, session_id: str, master: str, connection_manager: Any
) -> None:
    await asyncio.sleep(GRACE_SECONDS)
    tasks = _grace_tasks(session_manager)
    current = tasks.get(session_id)
    if current is not None and current is not asyncio.current_task():
        return
    tasks.pop(session_id, None)
    negotiator = get_negotiator(session_manager)
    if negotiator.master(session_id) != master or negotiator.master_attached(session_id):
        return
    await set_master(session_manager, session_id, None, connection_manager, reason="grace_expired")

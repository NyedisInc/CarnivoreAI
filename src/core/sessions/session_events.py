
from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Set

import structlog

from src.core.hosts.identity import parse_remote_session_id

logger = structlog.get_logger()

LISTENER_TIMEOUT_SECONDS = 5.0
STARTED, RENAMED, ENDED = "started", "renamed", "ended"


@dataclass(frozen=True)
class SessionEvent:

    kind: str
    tmux_name: str
    reason: str = ""
    session_row_id: Optional[int] = None
    session_uuid: Optional[str] = None
    old_name: str = ""
    display_name: str = ""
    project: str = ""
    agent_family: str = ""
    agent_type: str = ""
    ts: float = 0.0


Listener = Callable[[SessionEvent], Awaitable[None]]
_listeners: List[Listener] = []
_tasks: Set["asyncio.Task[None]"] = set()


def subscribe(listener: Listener) -> Callable[[], None]:
    _listeners.append(listener)

    def _remove() -> None:
        if listener in _listeners:
            _listeners.remove(listener)

    return _remove


async def emit(event: SessionEvent) -> None:
    for listener in list(_listeners):
        try:
            await asyncio.wait_for(listener(event), LISTENER_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("session_event_listener_timeout", kind=event.kind)
        except Exception as exc:
            logger.warning("session_event_listener_failed", kind=event.kind, error_type=type(exc).__name__)


def _identity(manager: Any, name: str) -> dict:
    from src.core.session_store import identity_for_live_name, sessions_table_ready, uuid_for_row

    conn = manager._datastore_connection()
    if conn is None:
        return {}
    try:
        if not sessions_table_ready(conn):
            return {}
        found = identity_for_live_name(conn, socket=manager.tmux_socket_name(), name=name)
        if not found:
            return {}
        return {"id": int(found["id"]), "uuid": uuid_for_row(conn, int(found["id"])),
                "project": found.get("project_name") or "", "family": found.get("agent_family") or "", "agent_type": found.get("agent_type") or ""}
    except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        logger.debug("session_event_identity_read_failed", error_type=type(exc).__name__)
        return {}
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


async def announce(manager: Any, kind: str, name: str, *, reason: str = "", old_name: str = "", display_name: str = "") -> None:
    if not _listeners or parse_remote_session_id(name) is not None:
        return
    found = await asyncio.to_thread(_identity, manager, name)
    await emit(SessionEvent(kind=kind, tmux_name=name, reason=reason, session_row_id=found.get("id"), session_uuid=found.get("uuid"), old_name=old_name,
                            display_name=display_name or name, project=found.get("project", ""), agent_family=found.get("family", ""), agent_type=found.get("agent_type", ""), ts=time.time()))


def schedule(manager: Any, kind: str, name: str, **kwargs: str) -> None:
    if not _listeners:
        return
    try:
        task = asyncio.get_running_loop().create_task(announce(manager, kind, name, **kwargs))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def schedule_stopped(manager: Any, session_uuids: Sequence[str]) -> None:
    if not _listeners or not session_uuids:
        return
    try:
        task = asyncio.get_running_loop().create_task(_announce_stopped(manager, tuple(session_uuids)))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _names_for(manager: Any, session_uuids: Sequence[str]) -> List[tuple]:
    conn = manager._datastore_connection()
    if conn is None:
        return []
    try:
        marks = ",".join("?" for _ in session_uuids)
        return [(int(r["id"]), r["session_uuid"], r["tmux_name"]) for r in conn.execute(
            f"SELECT id, session_uuid, tmux_name FROM sessions WHERE session_uuid IN ({marks})", tuple(session_uuids))]  # noqa: S608
    except sqlite3.Error as exc:
        logger.debug("session_event_stopped_read_failed", error_type=type(exc).__name__)
        return []
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


async def _announce_stopped(manager: Any, session_uuids: Sequence[str]) -> None:
    for row_id, uuid, name in await asyncio.to_thread(_names_for, manager, session_uuids):
        await emit(SessionEvent(kind=ENDED, tmux_name=name, reason="stopped", session_row_id=row_id, session_uuid=uuid, display_name=name, ts=time.time()))

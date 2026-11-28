
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

import structlog

from src.core.db import DatastoreUnreadableError
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError

logger = structlog.get_logger()

TABLE = "session_creators"

DDL_V106: Tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        session_uuid TEXT PRIMARY KEY,
        creator_uuid TEXT NOT NULL,
        created_at   TEXT NOT NULL
    )""",
)


def apply_v106(conn: sqlite3.Connection) -> None:
    for statement in DDL_V106:
        conn.execute(statement)


def _connect() -> sqlite3.Connection:
    from src.config import settings
    from src.core.db import connect, db_path_for

    return connect(db_path_for(settings.get_state_dir()), create=False)


def _store(session_uuid: str, creator_uuid: str) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(f"INSERT OR REPLACE INTO {TABLE} (session_uuid, creator_uuid, created_at) VALUES (?, ?, ?)",
                     (session_uuid, creator_uuid, datetime.now(timezone.utc).isoformat()))


def _read(session_uuid: str) -> Optional[str]:
    with closing(_connect()) as conn:
        row = conn.execute(f"SELECT creator_uuid FROM {TABLE} WHERE session_uuid = ?", (session_uuid,)).fetchone()
    return str(row[0]) if row and row[0] else None


async def _local_infos(manager: Any) -> list:
    return list(await manager.app.state.session_manager.list_session_infos())


async def caller_uuid(manager: Any, caller: AgentCaller) -> Optional[str]:
    if caller.from_token:
        return None
    for info in await _local_infos(manager):
        if info.host_key == "local" and (info.tmux_session == caller.tmux_name
                                         or info.session.id in (caller.session_id, caller.current_session_id)):
            return info.session_uuid or None
    return None


async def record(manager: Any, created_id: str, caller: AgentCaller) -> None:
    try:
        creator = await caller_uuid(manager, caller)
        created = next((i.session_uuid for i in await _local_infos(manager)
                        if i.host_key == "local" and i.session.id == created_id), None)
        if creator and created:
            await asyncio.to_thread(_store, created, creator)
    except (sqlite3.Error, OSError, DatastoreUnreadableError, ToolError, RuntimeError) as exc:
        logger.warning("mcp_session_creator_not_recorded", session_id=created_id, error_type=type(exc).__name__)


async def created_by_caller(manager: Any, caller: AgentCaller, session_uuid: Optional[str]) -> bool:
    if not session_uuid:
        return False
    try:
        stored = await asyncio.to_thread(_read, session_uuid)
        return bool(stored) and stored == await caller_uuid(manager, caller)
    except (sqlite3.Error, OSError, DatastoreUnreadableError, ToolError, RuntimeError) as exc:
        logger.warning("mcp_session_creator_unreadable", error_type=type(exc).__name__)
        return False

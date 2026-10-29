
from __future__ import annotations

import asyncio
import contextvars
import sqlite3
import time
from contextlib import closing
from typing import Any, Dict, List, Optional, Sequence

import structlog

from src.cplugs.sdk import AgentCaller, CplugContext

logger = structlog.get_logger()


_ACTING_KEY: "contextvars.ContextVar[str]" = contextvars.ContextVar("task_manager_acting_key", default="")

READ_MAX = 200


def acting_key() -> str:
    return _ACTING_KEY.get()


def by_for(actor: str, owner: str = "joe") -> str:
    return "owner" if actor == owner else (acting_key() or "claude")


def set_acting_key(key: str) -> "contextvars.Token[str]":
    return _ACTING_KEY.set(key)


def reset_acting_key(token: "contextvars.Token[str]") -> None:
    _ACTING_KEY.reset(token)


async def caller_key(ctx: CplugContext, caller: AgentCaller) -> Optional[str]:
    if caller.external or not caller.current_session_id:
        return None
    keys = await ctx.sessions.durable_keys()
    return keys.get(caller.current_session_id) or caller.current_session_id


def log_writes(store: Any, op: str, item_ids: Sequence[int], *, actor_key: str, session_id: str, cross: bool,
               now: Optional[float] = None) -> int:
    if not item_ids:
        return 0
    at = time.time() if now is None else now
    with closing(store._connect(True)) as conn, conn:
        conn.executemany("INSERT INTO work_write_actors (item_id, op, actor_key, actor_session_id, cross_project, at) VALUES (?,?,?,?,?,?)",
                         [(i, op, actor_key, session_id, int(cross), at) for i in item_ids])
    return len(item_ids)


def held_item(store: Any, actor_key: str, list_key: str) -> Optional[int]:
    if not actor_key:
        return None
    with closing(store._read_connection()) as conn:
        rows = conn.execute("SELECT id FROM work_items WHERE deleted = 0 AND claude_working = 1 AND claude_working_by = ? "
                            "AND list_key = ? LIMIT 2", (actor_key, list_key)).fetchall()
    return int(rows[0][0]) if len(rows) == 1 else None


def link_source(store: Any, item_id: int, source_item_id: int) -> bool:
    with closing(store._connect(True)) as conn, conn:
        return conn.execute("UPDATE work_items SET source_item_id = ? WHERE id = ? AND source_item_id IS NULL AND id != ?",
                            (source_item_id, item_id, source_item_id)).rowcount > 0


def actors_of(store: Any, item_id: int) -> Dict[str, Any]:
    with closing(store._read_connection()) as conn:
        source = conn.execute("SELECT source_item_id FROM work_items WHERE id = ?", (item_id,)).fetchone()
        rows = conn.execute("SELECT op, actor_key, actor_session_id, cross_project, at FROM work_write_actors WHERE item_id = ? "
                            "ORDER BY id LIMIT ?", (item_id, READ_MAX)).fetchall()
    return {"item_id": item_id, "source_item_id": source[0] if source else None,
            "actors": [{"op": r[0], "actor_key": r[1], "actor_session_id": r[2], "cross_project": bool(r[3]), "at": r[4]} for r in rows]}


async def record(ctx: CplugContext, caller: AgentCaller, store: Any, op: str, item_ids: List[int], *, cross: bool,
                 own_list_key: Optional[str]) -> None:
    if not item_ids:
        return
    key = await caller_key(ctx, caller) or ""
    session_id = "" if not caller.current_session_id else caller.current_session_id
    try:
        await asyncio.to_thread(log_writes, store, op, item_ids, actor_key=key or session_id, session_id=session_id, cross=cross)
        if cross and own_list_key is not None and op == "add":
            source = await asyncio.to_thread(held_item, store, key, own_list_key)
            if source is not None:
                for item_id in item_ids:
                    await asyncio.to_thread(link_source, store, item_id, source)
    except sqlite3.Error as exc:
        logger.warning("task_manager_actor_log_failed", op=op, items=item_ids, error_type=type(exc).__name__, error=str(exc))


from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict, Optional

import structlog

from src.cplugs.huddle import actor_log, kinds, service
from src.cplugs.huddle.roles.store import RoleStore
from src.cplugs.huddle.rules import CLAUDE, JOE, QUESTION, TaskManagerError
from src.cplugs.sdk import AgentCaller, CplugContext, ToolError

logger = structlog.get_logger()

CODE = "dnd_not_assigned"
FIELD = "reason"
MIN_REASON = 15
MAX_REASON = 500
SCHEMA = {FIELD: {"type": "string", "maxLength": MAX_REASON, "description": (
    f"Only on do not disturb, for a task not assigned to you (else refused: {CODE}; ask with task_manager_ask first): "
    f"why you must take it, {MIN_REASON}+ characters. Posted on the task for the owner.")}}
TOOLS = frozenset({"task_manager_update", "task_manager_reply", "task_manager_fork", "task_manager_artifact_add", "task_manager_progress_set"})


def refusal_text(item_id: int) -> str:
    return (f"refused ({CODE}): you are on do not disturb and item {item_id} is not assigned to you. Do not take it. Ask the owner with "
            f"task_manager_ask on item {item_id} (his answer lets you proceed, and so does his tagging it to you); if you must act now, "
            f"repeat this call with reason (at least {MIN_REASON} characters, why this task is yours to take); it is posted on the task for him")


def _assigned(conn: Any, item_id: int, key: str) -> Optional[bool]:
    row = conn.execute("SELECT tagged_session_key, created_key, claude_working_by FROM work_items WHERE id = ? AND deleted = 0", (item_id,)).fetchone()
    if row is None:
        return None
    if key in (row[0], row[1], row[2]):
        return True
    asked = conn.execute("SELECT MAX(id) FROM work_messages WHERE item_id = ? AND author = ? AND kind = ? AND author_key = ?",
                         (item_id, CLAUDE, QUESTION, key)).fetchone()[0]
    if asked is None:
        return False
    return conn.execute("SELECT 1 FROM work_messages WHERE item_id = ? AND author = ? AND id > ? LIMIT 1", (item_id, JOE, asked)).fetchone() is not None


def gate(store: Any, key: str, item_id: int) -> Optional[bool]:
    if key not in RoleStore(store).dnd_keys():
        return False
    with closing(store._read_connection()) as conn:
        assigned = _assigned(conn, item_id, key)
    return assigned is False


async def check(ctx: CplugContext, caller: AgentCaller, args: Dict[str, Any], reason: Any) -> None:
    item = args.get("item")
    if caller.external or not isinstance(item, int) or isinstance(item, bool):
        return
    key = await actor_log.caller_key(ctx, caller)
    store = service.store(ctx)
    if not key or not await asyncio.to_thread(gate, store, key, item):
        return
    text = reason.strip() if isinstance(reason, str) else ""
    if len(text) < MIN_REASON:
        logger.info("task_manager_dnd_claim_refused", session=key, item=item, given=bool(text))
        raise ToolError(refusal_text(item))
    note = f"do not disturb: this session took the task unassigned. Its reason: {text}"
    try:
        await asyncio.to_thread(lambda: store.post(item, note, actor=CLAUDE, kind=kinds.INFO, author_key=key, notify=True))
    except TaskManagerError as exc:
        raise ToolError(f"refused ({exc.code}): {exc}") from exc
    logger.info("task_manager_dnd_claim_allowed", session=key, item=item)

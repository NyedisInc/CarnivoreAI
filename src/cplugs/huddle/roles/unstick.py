
from __future__ import annotations

from contextlib import closing
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from src.cplugs.huddle import service, sending
from src.cplugs.huddle.roles import ask, route
from src.cplugs.sdk import CplugContext, session_bring_up

logger = structlog.get_logger()

Runner = Callable[[Callable[[], Any]], Awaitable[Any]]


def owning_key(store: Any, item_id: int) -> str:
    with closing(store._read_connection()) as conn:
        row = conn.execute("SELECT claude_working_by, tagged_session_key, owner_session_key FROM work_items WHERE id = ?", (item_id,)).fetchone()
    return (row[0] or row[1] or row[2] or "") if row else ""


def tag_key(store: Any, item_id: int) -> str:
    with closing(store._read_connection()) as conn:
        row = conn.execute("SELECT tagged_session_key FROM work_items WHERE id = ?", (item_id,)).fetchone()
    return (row[0] or "") if row else ""


async def send_session(ctx: CplugContext, run: Runner, key: str, list_key: str) -> Dict[str, Any]:
    found = await route.resolve(ctx, key) if key else None
    chosen = found.info.session.id if found is not None and found.ready else None
    infos = await ctx.sessions.list()
    return await sending.send_one_of_many(ctx, run, list_key, service.project_names(ctx).get(list_key), infos, chosen)


async def after_answer(ctx: CplugContext, run: Runner, posted: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    outcome = posted.get("carnivore")
    if not outcome or outcome["choice"] not in (ask.UNSTICK, ask.PUSH):
        return None
    list_key, item_id = posted["item"]["list"], posted["item"]["id"]
    if outcome["category"] in (ask.STALL, ask.WAIT_STUCK):
        key = await run(lambda: owning_key(service.store(ctx), item_id))
        told = await send_session(ctx, run, key, list_key)
    elif list_key.isdigit():
        try:
            chosen = await session_bring_up.wake_newest_or_start(ctx.sessions, int(list_key))
        except session_bring_up.BringUpFailed as exc:
            logger.warning("task_manager_unstick_bring_up_failed", list=list_key, error=str(exc))
            return None
        infos = await ctx.sessions.list()
        told = await sending.send_one_of_many(ctx, run, list_key, service.project_names(ctx).get(list_key), infos, chosen)
    else:
        infos = await ctx.sessions.list()
        told = await sending.send_one_of_many(ctx, run, list_key, service.project_names(ctx).get(list_key), infos, None)
    logger.info("task_manager_unstick_sent", list=list_key, item=item_id, category=outcome["category"], status=told["status"])
    return told


from __future__ import annotations

from typing import Optional

import structlog

from src.cplugs.huddle.roles import lead, route
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.session_rows import SessionRowsUnreadable

logger = structlog.get_logger()


async def row_stands(ctx: CplugContext, key: str) -> bool:
    try:
        rows = await ctx.sessions.stored_rows([key])
    except (SessionRowsUnreadable, PermissionError) as exc:
        logger.warning("task_manager_lost_rows_unreadable", error_type=type(exc).__name__)
        return True
    row = rows.get(key)
    return row is not None and not row.archived


async def lost_outcome(ctx: CplugContext, key: str, *, wake: bool) -> Optional[str]:
    if not key:
        return None
    found = await (route.resolve(ctx, key) if wake else route.peek(ctx, key))
    if found.ready or found.outcome in (route.LIVE, route.WOKEN, route.ASLEEP):
        return None
    if found.outcome == route.GONE and lead.fallback_agent_id(key) is None and await row_stands(ctx, key):
        return None
    return found.outcome

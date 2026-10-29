
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from src.cplugs.huddle import rules, service
from src.cplugs.huddle.roles import tags
from src.cplugs.sdk import CplugContext, ToolError

FIELD = "tag"
SCHEMA = {FIELD: {"type": "string", "description": (
    "'me' tags your own session, an agents_lookup id another agent, '' clears: the task is sent to that agent first, waking it if asleep "
    "(a gone agent: the project lead, else the owner). Guide section 29.")}}
CallerKey = Callable[[], Awaitable[Optional[str]]]


async def apply(ctx: CplugContext, item_id: int, value: Any, *, caller_key: CallerKey) -> Dict[str, Any]:
    if not isinstance(value, str):
        raise ToolError("tag is a string: 'me', an agent id from agents_lookup, or '' to clear")
    store = service.store(ctx)
    try:
        key = await tags.target_key(ctx, store, value, caller_key=await caller_key())
    except tags.TagRefused as exc:
        raise ToolError(str(exc)) from exc
    return await asyncio.to_thread(tags.set_tag, store, item_id, key)


async def tag_filer(ctx: CplugContext, item: Dict[str, Any], filer_key: Optional[str], *, external: bool) -> Dict[str, Any]:
    if external or not filer_key or filer_key == rules.SWARM_KEY:
        return item
    return await asyncio.to_thread(tags.set_tag, service.store(ctx), item["id"], filer_key)

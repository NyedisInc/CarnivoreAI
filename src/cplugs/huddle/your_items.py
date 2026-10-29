
from __future__ import annotations

import asyncio
import functools
import json
import time
from contextlib import closing
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.cplugs.huddle import own_list, rules, service
from src.cplugs.sdk import AgentCaller, CplugContext, scrub

CAP = 5
TITLE_LEN = 60
FIELD = "your_items"
MORE_FIELD = "your_items_more"

_SQL = (
    "SELECT * FROM ("
    "SELECT id, COALESCE(NULLIF(title, ''), text) AS label, 'working' AS held, updated_at FROM work_items "
    "WHERE deleted = 0 AND claude_working = 1 AND claude_working_by = ? "
    "UNION ALL "
    "SELECT id, COALESCE(NULLIF(title, ''), text), state, updated_at FROM work_items "
    "WHERE deleted = 0 AND list_key = ? AND state = ?) ORDER BY updated_at, id"
)


def held_rows(store: Any, key: Optional[str], list_key: Optional[str], now: Optional[float] = None) -> Dict[str, Any]:
    if not key and not list_key:
        return {}
    with closing(store._read_connection()) as conn:
        rows = conn.execute(_SQL, (key or "\0", list_key or "\0", rules.WAITING)).fetchall()
    if not rows:
        return {}
    at = time.time() if now is None else now
    seen, items = set(), []
    for row in rows:
        if row[0] in seen:
            continue
        seen.add(row[0])
        items.append({"id": row[0], "title": scrub(str(row[1])[:TITLE_LEN]), "state": row[2], "age_min": max(0, int((at - row[3]) // 60))})
    out: Dict[str, Any] = {FIELD: items[:CAP]}
    if len(items) > CAP:
        out[MORE_FIELD] = len(items) - CAP
    return out


async def for_caller(ctx: CplugContext, caller: AgentCaller, caller_key: Callable[..., Awaitable[Optional[str]]]) -> Dict[str, Any]:
    key = await caller_key(ctx, caller)
    if key is None:
        return {}
    list_key = await own_list.own_project(ctx, caller)
    return await asyncio.to_thread(held_rows, service.store(ctx), key, list_key)


def with_your_items(handler: Callable[..., Awaitable[dict]], caller_key: Callable[..., Awaitable[Optional[str]]]) -> Callable[..., Awaitable[dict]]:
    @functools.wraps(handler)
    async def wrapped(ctx: CplugContext, caller: AgentCaller, args: dict) -> dict:
        result = await handler(ctx, caller, args)
        if not isinstance(result, dict) or result.get("isError"):
            return result
        try:
            payload = json.loads(result["content"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError):
            return result
        if not isinstance(payload, dict):
            return result
        extra = await for_caller(ctx, caller, caller_key)
        return {**result, "content": [{**result["content"][0], "text": json.dumps({**payload, **extra}, default=str)}]} if extra else result

    return wrapped

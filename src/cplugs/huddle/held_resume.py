
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Callable, List

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import held, held_rows, sending, service
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()


async def _run(call: Callable[[], Any]) -> Any:
    return await asyncio.to_thread(call)


async def _candidates(ctx: CplugContext, key: str) -> List[dict]:
    try:
        return await service.candidate_rows(ctx, key)
    except (HTTPException, OSError, ValueError, RuntimeError) as exc:
        logger.warning("task_manager_held_resume_candidates_failed", list=key, error_type=type(exc).__name__)
        return []


async def resume(ctx: CplugContext) -> int:
    try:
        rows = await asyncio.to_thread(held_rows.load, service.store(ctx))
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_held_resume_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        return 0
    now, resumed = time.time(), 0
    for row in rows:
        if row["deadline"] <= now:
            held.restore_expired(ctx, row)
            continue
        key = row["list"]
        deliver = sending.held_deliver(ctx, _run, key, row["target"], await _candidates(ctx, key), row["params"])
        busy = HTTPException(status_code=409, detail={"code": row["code"], "detail": row["reason"]})
        held.hold(ctx, key, row["target"], row["label"], busy, deliver, params=row["params"], since=row["since"],
                  deadline=row["deadline"], grace_until=now + held.BOOT_GRACE_S)
        resumed += 1
    if rows:
        logger.info("task_manager_held_resumed", resumed=resumed, expired=len(rows) - resumed)
    return resumed


from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, List

import structlog

from src.cplugs.huddle import rules, service
from src.cplugs.huddle.rules import TaskManagerError

logger = structlog.get_logger()

HOLDER_KEY = "carnivore:approvals"


def retire_holders(store: Any) -> List[int]:
    with closing(store._read_connection()) as conn:
        ids = [int(r[0]) for r in conn.execute(
            "SELECT id FROM work_items WHERE created_key = ? AND deleted = 0 ORDER BY id", (HOLDER_KEY,))]
    retired: List[int] = []
    for item_id in ids:
        try:
            store.delete(item_id, actor=rules.JOE)
            retired.append(item_id)
        except TaskManagerError as exc:
            logger.info("task_manager_legacy_approvals_skipped", item=item_id, error=str(exc)[:120])
    return retired


async def retire(ctx: Any) -> int:
    try:
        retired = await asyncio.to_thread(retire_holders, service.store(ctx))
    except (sqlite3.Error, OSError) as exc:
        logger.warning("task_manager_legacy_approvals_failed", error=str(exc)[:200])
        return 0
    if retired:
        logger.info("task_manager_legacy_approvals_retired", count=len(retired), items=retired)
    return len(retired)

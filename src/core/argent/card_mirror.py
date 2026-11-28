
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Mapping

import structlog

from src.core.argent import close, work_items, writeback

logger = structlog.get_logger()

BOARD_REASON = "moved to done on the carnivore board"


def queue_picked(tenant: str, item_id: str, session_id: str = "") -> None:
    try:
        writeback.enqueue_move(tenant, item_id, writeback.MOVE_PICKED, session_id=session_id)
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.warning("argent_picked_mirror_failed", error_type=type(exc).__name__)


async def on_card_moved(before_column: str, card: Mapping[str, Any], reason: str = "") -> None:
    column = card.get("column")
    if column == before_column or column not in ("done", "in_progress") or not writeback.is_running():
        return
    item = close.item_of_origin(card.get("origin"))
    if not item:
        return
    try:
        tenant = await asyncio.to_thread(work_items.current_tenant)
        row = await asyncio.to_thread(work_items.resolve, tenant, item) if tenant else None
        if row is None:
            return
        if column == "done":
            await close.queue_close(tenant, str(row["id"]), " ".join(reason.split())[: close.MAX_REASON] or BOARD_REASON)
        elif row.get("kind") == "story":
            await asyncio.to_thread(queue_picked, tenant, str(row["id"]))
    except (sqlite3.Error, OSError) as exc:
        logger.warning("argent_card_mirror_failed", error_type=type(exc).__name__)

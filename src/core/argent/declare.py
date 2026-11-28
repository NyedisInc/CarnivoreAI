
from __future__ import annotations

import asyncio
import re
import sqlite3
from typing import Any, Dict

import structlog

from src.core.argent import card_mirror, session_ref, timeline, work_items, writeback

logger = structlog.get_logger()

SOURCES = ("picker", "mcp-self", "classifier", "card", "retag")
_AGENT_ID = re.compile(r"^[A-Za-z0-9._:-]{0,128}$")


class DeclareError(Exception):

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


async def declare(tmux_name: str, work_item_id: str, source: str, sub_agent_id: str = "") -> Dict[str, Any]:
    if source not in SOURCES:
        raise DeclareError("bad_source", f"source must be one of {', '.join(SOURCES)}")
    if not _AGENT_ID.match(sub_agent_id or ""):
        raise DeclareError("bad_sub_agent", "the sub-agent id is not a valid id")
    if not timeline.is_running():
        raise DeclareError("feature_off", "turn the argent feature on first")
    tenant = await asyncio.to_thread(work_items.current_tenant)
    if not tenant:
        raise DeclareError("login_required", "log in to argent first")
    item = await asyncio.to_thread(work_items.resolve, tenant, str(work_item_id or "").strip())
    if item is None:
        raise DeclareError("unknown_work_item", "that work item is not one argent has told this computer about")
    item_id = str(item["id"])
    ref = await asyncio.to_thread(session_ref.ref_for_name, tenant, tmux_name)
    queued = await asyncio.to_thread(timeline.record, tenant, ref, sub_agent_id or "", item_id, source)
    if queued is not None:
        timeline.poke()
    if queued is not None and not sub_agent_id:
        await _note_picked(tenant, ref, tmux_name, item_id, source, item.get("kind") == "story")
    declared = await asyncio.to_thread(timeline.current, tenant, ref)
    row = next((d for d in declared if d["sub_agent_id"] == (sub_agent_id or "")), None) or {}
    return {"session_id": ref, "sub_agent_id": sub_agent_id or "", "work_item_id": item_id, "ts": row.get("ts", ""),
            "reason": row.get("reason", source), "changed": queued is not None}


async def _note_picked(tenant: str, ref: str, tmux_name: str, item_id: str, source: str, is_story: bool) -> None:
    if is_story and source != "card":
        await asyncio.to_thread(card_mirror.queue_picked, tenant, item_id, ref)
    try:
        await asyncio.to_thread(writeback.enqueue_milestone, tenant, ref, tmux_name, tmux_name, item_id, writeback.PICKED, [])
        writeback.poke()
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.warning("argent_writeback_picked_failed", error_type=type(exc).__name__)


async def declare_at_create(tmux_name: str, story_ref: str) -> None:
    try:
        await declare(tmux_name, story_ref, "picker")
    except DeclareError as exc:
        logger.info("argent_declare_at_create_skipped", code=exc.code)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("argent_declare_at_create_failed", error_type=type(exc).__name__)

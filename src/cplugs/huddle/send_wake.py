
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from fastapi import HTTPException

from src.cplugs.huddle import service
from src.cplugs.huddle.roles import route, tag_send
from src.cplugs.sdk import CplugContext, session_bring_up

logger = structlog.get_logger()

WAKE_FAILED = "wake_failed"
WAKE_FAILED_REASON = "the session is asleep and did not wake"


class WakeFailed(Exception):
    pass


def needs_wake(key: str, rows: List[Dict[str, Any]]) -> bool:
    return key.isdigit() and not any(not r.get("elsewhere") for r in rows)


async def wake_project(ctx: CplugContext, key: str) -> Optional[str]:
    try:
        return await session_bring_up.wake_newest(ctx.sessions, int(key))
    except (HTTPException, session_bring_up.BringUpFailed) as exc:
        logger.warning("task_manager_send_wake_failed", list=key, error_type=type(exc).__name__)
        raise WakeFailed(str(exc)) from exc


async def rows_after_wake(ctx: CplugContext, key: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not needs_wake(key, rows) or await wake_project(ctx, key) is None:
        return rows
    return await service.candidate_rows(ctx, key)


async def rows_with_lead(ctx: CplugContext, run: Any, key: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def to_wake() -> str:
        pick = service.store(ctx).send_pick(key)
        return "" if pick and any(r["key"] == pick for r in rows) else route.lead_to_wake(service.store(ctx), rows, key)

    holder = await run(to_wake)
    if not holder:
        return rows
    found = await route.resolve(ctx, holder)
    if not found.ready:
        logger.info("task_manager_send_lead_not_woken", list=key, outcome=found.outcome)
        return rows
    fresh = await service.candidate_rows(ctx, key)
    if any(r["key"] == holder for r in fresh):
        return fresh
    return [r for r in fresh if not r.get("elsewhere")] + [tag_send.candidate_of(found.info, holder)]


def failed_outcome(key: str) -> Dict[str, Any]:
    return {"list": key, "status": "refused", "code": WAKE_FAILED, "reason": WAKE_FAILED_REASON}


from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import structlog

from src.plugins.taskmanager.roles import route
from src.plugins.sdk import CplugContext, session_bring_up

logger = structlog.get_logger()

MARK_TTL_S = 15 * 60.0
_WOKEN: Dict[str, float] = {}


def _mark(session_id: str, now: Optional[float] = None) -> None:
    now = time.monotonic() if now is None else now
    for stale in [k for k, at in _WOKEN.items() if now - at > MARK_TTL_S]:
        del _WOKEN[stale]
    _WOKEN[session_id] = now


async def resolve_lead(ctx: CplugContext, lead_key: str) -> Optional[Any]:
    found = await route.resolve(ctx, lead_key)
    if found.outcome == route.GONE or (found.ready and not session_bring_up.can_take(found.info)):
        return None
    if not found.ready:
        raise session_bring_up.BringUpFailed(f"the lead did not wake ({found.outcome})")
    if found.outcome == route.WOKEN:
        _mark(found.info.session.id)
        logger.info("task_manager_lead_woken", session_id=found.info.session.id)
    return found.info


def waker(ctx: CplugContext) -> session_bring_up.LeadWaker:
    async def wake(lead_key: str) -> Optional[str]:
        info = await resolve_lead(ctx, lead_key)
        return info.session.id if info is not None else None

    return wake


async def wake_lead(ctx: CplugContext, list_key: str, lead_key: str) -> Optional[Any]:
    async with session_bring_up.project_lock(int(list_key)):
        try:
            return await resolve_lead(ctx, lead_key)
        except session_bring_up.BringUpFailed as exc:
            logger.info("task_manager_lead_not_woken", list=list_key, error=str(exc)[:200])
            return None


def others_line(rows: List[Dict[str, Any]], target: str) -> str:
    others = [r for r in rows if r["id"] != target and not r.get("elsewhere") and r.get("activity_status") != "dead"]
    if not others:
        return ""
    names = ", ".join(f"{r['label']} ({r['id']})" for r in others)
    return (f"you were woken as this project's lead, and another agent of the project is already running: {names}. "
            "decide: hand the work to it, or carry on yourself. ")


def note_for(target: str, rows: List[Dict[str, Any]]) -> str:
    at = _WOKEN.pop(target, None)
    if at is None or time.monotonic() - at > MARK_TTL_S:
        return ""
    return others_line(rows, target)


from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.api import beast_mode_routes
from src.api.auth import require_auth
from src.core.automations import pause
from src.core.swarm import switch

logger = structlog.get_logger()
router = APIRouter(prefix="/autonomy", tags=["autonomy"], dependencies=[Depends(require_auth)])

_STEP_ERRORS = (FileNotFoundError, ValueError, OSError, HTTPException)


class StandDownResult(BaseModel):
    """What stood down. Each flag is True when that part is now off or paused; ``failed`` names the steps that did not land."""

    beast_off: bool
    swarm_off: bool
    scheduler_paused: bool
    failed: List[str] = []


async def _step(name: str, action: Callable[[], Awaitable[bool]]) -> bool:
    try:
        return await action()
    except _STEP_ERRORS as exc:
        logger.error("stand_down_step_failed", step=name, error_type=type(exc).__name__)
        return False


@router.post("/stand-down", response_model=StandDownResult)
async def post_stand_down(request: Request):
    """Beast Mode off, Swarm off, scheduler paused. Alerts and notifications are untouched.

    Output: {"beast_off", "swarm_off", "scheduler_paused", "failed": [step names]}. 200 when at least one step
      landed (read ``failed`` for the rest); 500 with the same body when every step failed.
    Example: POST /api/v1/autonomy/stand-down -> {"beast_off": true, "swarm_off": true, "scheduler_paused": true, "failed": []}
    """

    async def beast() -> bool:
        answer = await beast_mode_routes.set_beast_mode(beast_mode_routes.BeastSetting(enabled=False), "stand_down")
        return not answer["enabled"]

    async def swarm() -> bool:
        answer = await switch.set_enabled(getattr(request.app, "state", None), False)
        return not answer["enabled"]

    async def scheduler() -> bool:
        return bool(await asyncio.to_thread(pause.set_paused, True))

    flags = {
        "beast_off": await _step("beast_off", beast),
        "swarm_off": await _step("swarm_off", swarm),
        "scheduler_paused": await _step("scheduler_paused", scheduler),
    }
    result = StandDownResult(**flags, failed=[name for name, ok in flags.items() if not ok])
    logger.info("stand_down", **result.model_dump())
    if len(result.failed) == len(flags):
        return JSONResponse(status_code=500, content=result.model_dump())
    return result

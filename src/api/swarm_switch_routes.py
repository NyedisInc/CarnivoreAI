
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.core.swarm import switch

logger = structlog.get_logger()
router = APIRouter(prefix="/swarm/switch", tags=["swarm"], dependencies=[Depends(require_auth)])


class SwarmSwitchSetting(BaseModel):
    """The owner's desired switch state. Example: {"enabled": false}"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


def require_swarm_on() -> None:
    if not switch.is_on():
        raise HTTPException(status_code=409, detail=switch.refusal())


async def refuse_held_body(session_uuid: str) -> None:
    if await run_in_threadpool(switch.guards_body, session_uuid):
        raise HTTPException(status_code=409, detail=switch.refusal())


@router.get("")
async def get_swarm_switch() -> Dict[str, Any]:
    """Whether the Swarm runs on this computer. Output: {"enabled": bool}. Example: GET /api/v1/swarm/switch -> {"enabled": true}"""
    return switch.status()


@router.put("")
async def put_swarm_switch(body: SwarmSwitchSetting, request: Request) -> Dict[str, Any]:
    """Turn the Swarm on or off for this whole computer. Inputs: body; request (for the app state a turn-on resumes).

    Output: {"enabled": bool}, the state after the write. Raises: HTTPException 500 when config.json cannot be written.
    Example: PUT /api/v1/swarm/switch {"enabled": false} -> {"enabled": false}
    """
    try:
        return await switch.set_enabled(getattr(request.app, "state", None), body.enabled)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.error("swarm_switch_unwritable", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="config.json could not be updated") from exc

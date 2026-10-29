
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.api.auth import require_auth
from src.config import settings
from src.core.event_hub import get_hub
from src.core.perf_hooks import sampler
from src.core.perf_hooks.monitor import PERF
from src.api.error_response import api_error

logger = structlog.get_logger()

router = APIRouter(prefix="/dev", tags=["dev"])


class PerfSwitch(BaseModel):
    """The body of `PUT /dev/perf`."""

    enabled: bool


class ProfileBody(BaseModel):
    """The body of `POST /dev/perf/profile`: the window, the tick rate, rows per table."""

    seconds: float = Field(default=30.0, ge=sampler.MIN_SECONDS, le=sampler.MAX_SECONDS)
    hz: int = Field(default=sampler.DEFAULT_HZ, ge=sampler.MIN_HZ, le=sampler.MAX_HZ)
    top: int = Field(default=sampler.DEFAULT_TOP, ge=1, le=sampler.MAX_TOP)


def _state() -> Dict[str, Any]:
    return {
        "enabled": PERF.enabled,
        "configured": bool(settings.dev_perf_hooks),
        "sample": PERF.last_frame,
    }


def start_if_configured(app_state: Any) -> bool:
    if not settings.dev_perf_hooks:
        return False
    hub = get_hub(app_state)
    PERF.enable(hub.publish if hub else None)
    return True


@router.get("/perf", dependencies=[Depends(require_auth)])
async def get_perf() -> Dict[str, Any]:
    """Whether the hooks are on, and the most recent `perf.sample` frame."""
    return _state()


@router.put("/perf", dependencies=[Depends(require_auth)])
async def put_perf(body: PerfSwitch, request: Request) -> Dict[str, Any]:
    """Turn the hooks on or off now. Idempotent; not persisted across a restart."""
    if body.enabled:
        hub = get_hub(request.app.state)
        PERF.enable(hub.publish if hub else None)
    else:
        PERF.disable()
    logger.info("perf_hooks_switched", enabled=PERF.enabled)
    return _state()


@router.post("/perf/profile", dependencies=[Depends(require_auth)])
async def post_profile(body: ProfileBody) -> Dict[str, Any]:
    """Sample this server for `seconds` and answer where its CPU went. Blocks for the window.

    Inputs: body (ProfileBody). Output: the `sampler.run_profile` dict.
    Raises: HTTPException 409 while another profile runs.
    """
    try:
        return await sampler.profile(sampler.ProfileRequest(seconds=body.seconds, hz=body.hz, top=body.top))
    except sampler.ProfileBusyError as exc:
        raise api_error(409, "conflict", exc, step="post_profile") from exc

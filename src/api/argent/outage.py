
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from src.api.argent.status import feature_on
from src.api.auth import require_auth
from src.core.argent import outage, rollout

router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])


def _refuse(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message})


@router.get("/outage")
async def get_outage() -> Dict[str, Any]:
    """The outage view. Example: GET /api/v1/argent/outage -> {"enabled": true, "active": true, "reason": "gateway down", "tethered": 4}"""
    if not feature_on():
        return {"enabled": False, "active": False, "reason": "", "since": None, "tethered": 0, "key_expiring": 0, "rollout_paused": False}
    tenant = await run_in_threadpool(rollout.tenant_id)
    return {"enabled": True, **await run_in_threadpool(outage.view_sync, tenant)}


@router.post("/outage/restart-direct")
async def post_restart_direct(request: Request) -> Dict[str, Any]:
    """Restart every tethered local session as a resume now (idle ones; busy ones are counted as waiting). Output: {restarted, waiting}. Raises: 409 ``feature_off``, ``no_outage``."""
    if not feature_on():
        raise _refuse("feature_off", "turn the argent feature on first")
    manager = getattr(request.app.state, "session_manager", None)
    if manager is None:
        raise _refuse("no_outage", "no session manager")
    try:
        return await outage.restart_direct(manager)
    except LookupError:
        raise _refuse("no_outage", "the gateway is not down") from None

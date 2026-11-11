
from __future__ import annotations

from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.argent.status import feature_on
from src.api.auth import require_auth
from src.core.argent import pair_sync, rollout, rollout_preview, settings as settings_module

router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])


class RestartNow(BaseModel):
    """The owner's restart of one waiting row; the modal's armed checkbox is the confirmation. Example: {"tmux_name": "carnivore_api"}"""

    model_config = ConfigDict(extra="forbid")

    tmux_name: str = Field(min_length=1, max_length=200)


class RolloutAction(BaseModel):
    """One owner action. Example: {"action": "start"}"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["start", "cancel", "resume"]


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _view() -> Dict[str, Any]:
    tenant = await run_in_threadpool(rollout.tenant_id)
    return {"enabled": True, **await run_in_threadpool(rollout.view_sync, tenant)}


@router.get("/rollout")
async def get_rollout() -> Dict[str, Any]:
    """The rollout's state, direction, per-state and per-reason counts and every row. Example: GET /api/v1/argent/rollout -> {"state": "running", "counts": {"pending": 2}}"""
    if not feature_on():
        return {"enabled": False, "state": "off", "direction": "", "epoch": 0, "reason": "", "counts": {}, "reasons": {}, "rows": []}
    return await _view()


@router.get("/rollout/preview")
async def get_rollout_preview(request: Request) -> Dict[str, Any]:
    """Counts of what a rollout in the switch's direction would restart and what it cannot change. Example: GET /api/v1/argent/rollout/preview -> {"will_restart": 4, "excluded": {"settings override": 1}}"""
    if not feature_on():
        return {"enabled": False, **rollout_preview.EMPTY, "direction": ""}
    manager = getattr(request.app.state, "session_manager", None)
    cfg = await run_in_threadpool(settings_module.read)
    direction = "on" if cfg.enabled else "off"
    if manager is None:
        return {"enabled": True, **rollout_preview.EMPTY, "direction": direction}
    tenant = await run_in_threadpool(rollout.tenant_id)
    return {"enabled": True, **await rollout_preview.preview(manager, tenant, direction)}


@router.post("/rollout")
async def post_rollout(body: RolloutAction, request: Request) -> Dict[str, Any]:
    """Start, cancel or resume the rollout. Output: the view after. Raises: 409 ``feature_off``, ``not_logged_in`` (an ON rollout mints keys), ``nothing_to_cancel``, ``nothing_paused``."""
    if not feature_on():
        raise _refuse(409, "feature_off", "turn the argent feature on first")
    rollout.bind(request.app.state)
    if body.action == "start":
        cfg = await run_in_threadpool(settings_module.read)
        if cfg.enabled and not await run_in_threadpool(rollout.tenant_id):
            raise _refuse(409, "not_logged_in", "log in to argent first")
        await rollout.begin("on" if cfg.enabled else "off")
        await pair_sync.rollout_started()
    elif body.action == "cancel":
        if not await rollout.cancel():
            raise _refuse(409, "nothing_to_cancel", "no rollout is running")
    elif not await rollout.resume():
        raise _refuse(409, "nothing_paused", "no rollout is paused")
    if body.action != "cancel":
        rollout.ensure_running()
    return await _view()


@router.post("/rollout/restart-now")
async def post_restart_now(body: RestartNow, request: Request) -> Dict[str, Any]:
    """Restart one waiting row onto (or off) the gateway as a resume now, past the rest and quiet gates; the conversation rules stay. Output: the view after. Raises: 409 ``feature_off``, ``no_rollout``, ``not_open``, ``not_found``, ``refused``."""
    if not feature_on():
        raise _refuse(409, "feature_off", "turn the argent feature on first")
    manager = getattr(request.app.state, "session_manager", None)
    if manager is None:
        raise _refuse(409, "not_found", "no session manager")
    result = await rollout.restart_now(manager, body.tmux_name)
    if result != "ok":
        raise _refuse(409, result, "that row cannot be restarted now" if result == "refused" else "that row is not waiting in the current rollout")
    return await _view()

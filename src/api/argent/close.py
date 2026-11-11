
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.api.error_response import refusal_error
from src.api.remote_route_guard import refuse_remote
from src.core.argent import close as close_module
from src.core.argent import retag as retag_module

router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])


class CloseBody(BaseModel):
    """Example: {"reason": "shipped in 1.4"}"""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field("", max_length=close_module.MAX_REASON * 2)


class RetagBody(BaseModel):
    """Example: {"session_id": "ses_abc", "since": "2026-11-01T00:00:00Z", "until": "2026-11-02T00:00:00Z", "work_item_id": "wi_story2", "reason": "wrong story picked"}"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1, max_length=200)
    since: str = Field(..., min_length=10, max_length=40)
    until: str = Field(..., min_length=10, max_length=40)
    work_item_id: str = Field(..., min_length=1, max_length=200)
    reason: str = Field(..., max_length=close_module.MAX_REASON * 2)


def _http(exc: close_module.Refused) -> HTTPException:
    return refusal_error(exc, extra={"message": exc.message})


@router.post("/work-items/{item_id}/close")
async def close_work_item(item_id: str, body: CloseBody) -> Dict[str, Any]:
    """Close an item. Output: {work_item_id, closed, status_refused}.

    Raises: 409 ``feature_off``, 403 ``login_required`` or ``login_expired``, 404 ``unknown_work_item``, 422 ``bad_reason`` or ``blocked_secret``, 502 ``argent_unreachable``, 503 ``unavailable``, or Argent's own 4xx.
    Example: POST /api/v1/argent/work-items/wi_story1/close {"reason": "shipped in 1.4"}
    """
    try:
        return await close_module.close_item(item_id, body.reason)
    except close_module.Refused as exc:
        raise _http(exc) from None


@router.post("/retag")
async def retag(request: Request, body: RetagBody) -> Dict[str, Any]:
    """Re-tag a session's spend in a window. Output: Argent's {ok, moved_micros, from_work_item_id, to_work_item_id, log_id}.

    Raises: 404 ``session_not_found``, ``not_own_session`` or ``unknown_work_item``, 409 ``feature_off`` or ``remote_host``, 422 ``bad_range``, ``range_too_long``, ``bad_reason`` or ``blocked_secret``, plus the close route's.
    Example: POST /api/v1/argent/retag {"session_id": "ses_abc", "since": "2026-11-01T00:00:00Z", "until": "2026-11-02T00:00:00Z", "work_item_id": "wi_story2", "reason": "wrong story picked"}
    """
    manager = request.app.state.session_manager
    refuse_remote(manager, body.session_id, "an argent re-tag")
    info = await manager.get_session_info(body.session_id)
    if info is None or not info.tmux_session:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": f"No session with id {body.session_id!r}"})
    try:
        return await retag_module.retag(str(info.tmux_session), body.since, body.until, body.work_item_id, body.reason)
    except close_module.Refused as exc:
        raise _http(exc) from None

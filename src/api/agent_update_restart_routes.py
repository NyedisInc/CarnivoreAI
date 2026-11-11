
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.auth import require_auth
from src.core.notifications.sources import agent_update, toast as toast_source
from src.core.notify_caps import effects

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


class RestartAgentsBody(BaseModel):
    """The card being pressed: ``toast_id`` is the id of the agent-update toast the banner shows."""

    toast_id: str


@router.post("/agent-update/restart")
async def restart_stale_agents(body: RestartAgentsBody, request: Request) -> Dict[str, Any]:
    """Restart the idle sessions the named agent-update toast lists, and no others.

    Output: ``{"state": "sent", "restarted": n, "skipped": m}``. Raises: HTTPException 404 - no such toast; 422 - the toast is not an agent
    update; 409 ``nothing_restarted`` - none of its sessions was idle enough to restart.
    Example: POST /api/v1/notifications/agent-update/restart {"toast_id": "3f2a..."} -> 200 {"restarted": 2, "skipped": 1}
    """
    event = toast_source.event_for_toast_id(request.app.state.session_manager, body.toast_id)
    if event is None:
        raise HTTPException(status_code=404, detail="no such notification")
    if event.type_id != agent_update.TYPE_ID:
        raise HTTPException(status_code=422, detail="not an agent update notification")
    ids = [str(i) for i in ((event.card_hint or {}).get("ids") or [])][:50]
    status, answer = await effects.restart_agents(request.app.state, ids)
    if status != 200:
        raise HTTPException(status_code=status, detail=answer)
    return answer

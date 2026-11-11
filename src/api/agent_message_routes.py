
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.error_response import api_error
from src.api.agent_auth import require_agent
from src.core.mcp.caller import AgentCaller
from src.core.notifications import agent_message

logger = structlog.get_logger()

router = APIRouter(tags=["agent-message"])


class AgentMessageBody(BaseModel):
    """The message text (at most 280 characters once control characters are stripped) and an optional attachment.

    ``type`` is ``agent.message`` or ``agent.review``; a review needs an ``attachment`` (422 ``bad_attachment`` without one).
    ``attachment`` is ``{"path": "/abs/file"}`` (a file, image or video inside the session's project) or ``{"url": "https://..."}``
    (a link, never fetched), each with an optional ``title`` (120 characters, shown as the agent's words). It is checked in
    ``notify_media.intake``: 422 ``outside_project``, ``secret_found``, ``bad_url``, ``bad_attachment``; 413 ``too_large``.
    """

    text: str
    attachment: Optional[Dict[str, Any]] = None
    type: Literal["agent.message", "agent.review"] = "agent.message"


def refusal_for(caller: AgentCaller) -> str:
    if caller.external:
        return "agent notify is for a running pane, not an external token"
    if caller.scope != "write":
        return "agent notify needs a write credential"
    return ""


@router.post("/sessions/{session_id}/agent-message", status_code=201)
async def post_agent_message(
    request: Request, session_id: str, body: AgentMessageBody, caller: AgentCaller = Depends(require_agent)
) -> Dict[str, Any]:
    """Record one agent message toast for the caller's own session.

    Inputs: session_id (path); body (AgentMessageBody); caller (from the token).
    Output: {sent, toast_id}. Raises: 403 (external or read token, another session's path, switch off),
      404 (session not live), 413 (attachment too large), 422 (empty or over-long text, refused attachment), 429 with Retry-After.
    """
    why = refusal_for(caller)
    if why:
        raise HTTPException(status_code=403, detail=why)
    if session_id not in (caller.session_id, caller.current_session_id):
        raise HTTPException(status_code=403, detail="an agent may only notify about its own session")
    try:
        return await agent_message.send(request.app.state.session_manager, caller.current_session_id, body.text, attachment=body.attachment, app_state=request.app.state, review=body.type == "agent.review")
    except agent_message.AgentNotifyError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        raise api_error(exc.status, "agent_notify_refused", exc, headers=headers,
                        extra={"reason": exc.reason} if exc.reason else None, session=caller.session_id) from exc

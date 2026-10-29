
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.agent_auth import require_agent
from src.core.mcp.caller import AgentCaller
from src.core.notifications import agent_message

logger = structlog.get_logger()

router = APIRouter(tags=["agent-message"])


class AgentMessageBody(BaseModel):
    """The message text (at most 280 characters once control characters are stripped)."""

    text: str


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
      404 (session not live), 422 (empty or over-long text), 429 with Retry-After.
    """
    why = refusal_for(caller)
    if why:
        raise HTTPException(status_code=403, detail=why)
    if session_id not in (caller.session_id, caller.current_session_id):
        raise HTTPException(status_code=403, detail="an agent may only notify about its own session")
    try:
        return await agent_message.send(request.app.state.session_manager, caller.current_session_id, body.text)
    except agent_message.AgentNotifyError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        raise HTTPException(status_code=exc.status, detail=exc.message, headers=headers) from exc

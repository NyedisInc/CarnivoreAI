
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.agent_auth import require_agent
from src.api.messaging_routes import runtime_of
from src.core.mcp.caller import AgentCaller
from src.core.messaging import outbound, store

logger = structlog.get_logger()

router = APIRouter(tags=["messaging"])


class SendBody(BaseModel):
    """The text, and the conversation when the session has more than one outbound binding."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=8000)
    conversation_id: Optional[str] = None


async def _caller_identity(request: Any, caller: AgentCaller) -> tuple[str, str]:
    info = await request.app.state.session_manager.get_session_info(session_id=caller.current_session_id)
    uuid = store.uuid_for_row(info.session_row_id) if info is not None else None
    if uuid is None and info is not None and info.session_row_id is not None:
        from src.core.crosstalk.directory import _session_details

        details = await asyncio.to_thread(_session_details, [info.session_row_id])
        uuid = details.get(info.session_row_id, (None,))[0]
    if info is None or not uuid:
        raise HTTPException(status_code=403, detail={"code": "not_bound"})
    name = (info.label or "").strip() or (info.claude_title or "").strip() or info.tmux_session or info.session.id
    return str(uuid), str(name)


async def send_for_caller(request: Any, caller: AgentCaller, body: SendBody) -> Dict[str, Any]:
    if caller.external or caller.scope != "write":
        raise HTTPException(status_code=403, detail={"code": "not_bound"})
    rt = runtime_of(request)
    uuid, name = await _caller_identity(request, caller)
    try:
        return await outbound.send_as_session(rt, session_uuid=uuid, session_name=name, text=body.text,
                                              conversation_id=body.conversation_id)
    except outbound.SendRefused as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        detail = {"code": exc.code, **({"reason": exc.reason} if exc.reason else {})}
        raise HTTPException(status_code=exc.status, detail=detail, headers=headers) from None


@router.post("/sessions/{session_id}/messaging/send", status_code=201)
async def post_messaging_send(request: Request, session_id: str, body: SendBody,
                              caller: AgentCaller = Depends(require_agent)) -> Dict[str, Any]:
    """Send one text to the owner as the calling session. Raises 403 for another session's path."""
    if session_id not in (caller.session_id, caller.current_session_id):
        raise HTTPException(status_code=403, detail={"code": "not_your_session"})
    return await send_for_caller(request, caller, body)

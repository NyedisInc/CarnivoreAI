
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.mcp_health_listing import mcp_health_for_row
from src.api.one_shot_routes import paste_through_gates
from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.agent_families import DEFAULT_FAMILY
from src.core.mcp_health.reconnect import ReconnectRefused, reconnect_command
from src.core.session_one_shot_gate import PROMPT_READY_STATUSES

logger = structlog.get_logger()
router = APIRouter()

REFUSE_NOT_CLAUDE: str = "not_claude"
REFUSE_BUSY: str = "session_busy"


class McpReconnectRequest(BaseModel):
    """Body of the reconnect route. ``server`` names one dropped server; omitted means every dropped one."""
    server: Optional[str] = Field(default=None, max_length=200, description="One dropped server's name, or omit for all")


class McpReconnectResponse(BaseModel):
    """What was typed. ``command`` is the exact slash command; ``servers`` the dropped names it covers."""
    sent: bool
    command: str
    servers: List[str]


def _refuse(session_id: str, code: str, message: str) -> HTTPException:
    logger.info("mcp_reconnect_refused", session_id=session_id, code=code, reason=message)
    return HTTPException(status_code=409, detail={"code": code, "message": message})


@router.post(
    "/sessions/{session_id}/mcp/reconnect",
    response_model=McpReconnectResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def reconnect_mcp(request: Request, session_id: str, body: McpReconnectRequest) -> McpReconnectResponse:
    """Type ``/mcp reconnect`` into an idle claude session for its dropped MCP servers.

    Description: see the module docstring. Reads the row and its fold, refuses unless the session is idle at
      its prompt, then pastes the command through the guarded path. Nothing is written on any refusal.
    Inputs: request (Request). session_id (str) - either id shape. body (McpReconnectRequest).
    Output: McpReconnectResponse.
    Raises: HTTPException 404 unknown session; 409 ``{code, message}`` per refusal.
    Example: POST /api/v1/sessions/ses_abc/mcp/reconnect {"server": "carnivore"}
    """
    manager = request.app.state.session_manager
    refuse_remote(manager, session_id, "reconnecting MCP servers")
    info = await manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    if info.agent_family is not None and info.agent_family != DEFAULT_FAMILY:
        raise _refuse(session_id, REFUSE_NOT_CLAUDE, "MCP reconnect is only offered for a claude session")
    if info.activity_status not in PROMPT_READY_STATUSES:
        raise _refuse(session_id, REFUSE_BUSY, "the session is busy; wait until it is idle at its prompt")
    health = mcp_health_for_row(request.app.state, info, datetime.now(timezone.utc))
    try:
        command = reconnect_command(health, body.server)
    except ReconnectRefused as refusal:
        raise _refuse(session_id, refusal.code, refusal.message) from refusal
    await paste_through_gates(request, session_id, command, idle_only=True, fresh_dialog_check=True)
    servers = [d.name for d in health.dropped] if health is not None else []
    logger.info("mcp_reconnect_sent", session_id=session_id, command=command, servers=servers)
    return McpReconnectResponse(sent=True, command=command, servers=servers)

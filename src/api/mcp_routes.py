
from __future__ import annotations

import hashlib

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.requests import ClientDisconnect

from slowapi.util import get_remote_address

from src.api.agent_auth import SESSION_HEADER, require_agent
from src.api.auth import limiter
from src.api.request_log import LOG_EXTRA_KEY
from src.config import settings
from src.core.mcp import channel as channel_events
from src.core.mcp import protocol, token_store
from src.core.mcp.caller import AgentCaller

logger = structlog.get_logger()
router = APIRouter()

CLIENT_CLOSED_STATUS = 499


def mcp_enabled() -> None:
    try:
        enabled = settings.load_auth_config().mcp.enabled
    except (ValueError, OSError) as exc:
        logger.warning("mcp_config_unreadable", error=str(exc))
        enabled = False
    if not enabled:
        raise HTTPException(status_code=404, detail="Not Found")


def _rate_key(request: Request) -> str:
    value = request.headers.get("authorization", "")
    if value[:7].lower() == "bearer " and token_store.is_token(value[7:].strip()):
        return "tok:" + hashlib.sha256(value[7:].strip().encode()).hexdigest()[:16]
    return request.headers.get(SESSION_HEADER) or get_remote_address(request)


@router.post("/mcp", dependencies=[Depends(mcp_enabled)])
@limiter.limit("600/minute", key_func=_rate_key)
async def mcp_post(
    request: Request, caller: AgentCaller = Depends(require_agent)
) -> Response:
    """Handle one JSON-RPC message or batch from an authenticated agent.

    Inputs: request (Request); caller (AgentCaller) - from ``require_agent``.
    Output: JSON reply, or 202 with no body for notifications, 499 when the client hung up mid-body (nobody reads it), 413 when the
      body is over the cap (``protocol.MAX_BODY_BYTES``, or a larger one only for one call of a tool that takes files inline,
      ``protocol.body_allowed``; nothing past ``protocol.MAX_READ_BYTES`` is ever read).
    """
    too_large = JSONResponse({"error": "request too large"}, status_code=413)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > protocol.MAX_READ_BYTES:
        return too_large
    chunks: list[bytes] = []
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > protocol.MAX_READ_BYTES:
                return too_large
            chunks.append(chunk)
    except ClientDisconnect:
        logger.debug("mcp_client_disconnected", route=request.url.path, client=get_remote_address(request), bytes_read=size)
        return Response(status_code=CLIENT_CLOSED_STATUS)
    raw = b"".join(chunks)
    if not protocol.body_allowed(raw, caller):
        return too_large
    request.scope[LOG_EXTRA_KEY] = {"rpc": protocol.rpc_methods(raw)}
    status, payload, headers = await protocol.handle_body(
        raw, request.app.state.session_manager, caller, request.app, channel=_channel_caller(request, caller),
        session_id=request.headers.get(protocol.SESSION_ID_HEADER),
    )
    if payload is None:
        return Response(status_code=status, headers=headers)
    return JSONResponse(payload, status_code=status, headers=headers)


def _channel_caller(request: Request, caller: AgentCaller) -> bool:
    return (not caller.external and channel_events.channel_requested(request.headers)
            and channel_events.channels_enabled())


@router.get("/mcp", dependencies=[Depends(mcp_enabled)])
async def mcp_stream(request: Request) -> Response:
    """The Claude Code channel stream for a channel launch; 405 for everyone else, as before.

    Description: authenticated like ``POST /mcp`` (the pane's hook token) but only AFTER the cheap header and setting
      checks, so a non-channel client still gets the silent 405 it always got. The stream is registered under the
      token's tmux name and carries ``notifications/claude/channel`` events (``channel.REGISTRY.push``).
    Inputs: request (Request). Output: an SSE stream, or 405 with ``Allow: POST``.
    Raises: HTTPException 401 or 403 from ``require_agent`` for a channel request with a bad credential.
    """
    if not (channel_events.channel_requested(request.headers) and channel_events.channels_enabled()):
        return Response(status_code=405, headers={"Allow": "POST"})
    caller = await require_agent(request)
    if caller.external:
        return Response(status_code=405, headers={"Allow": "POST"})
    body = channel_events.stream_events(caller.tmux_name, caller.current_session_id,
                                        fingerprint=lambda: protocol.tool_fingerprint(caller, True))
    return StreamingResponse(body, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.delete("/mcp", dependencies=[Depends(mcp_enabled)])
async def mcp_no_teardown() -> Response:
    """No session teardown (the server keeps no MCP session state): 405, POST only.

    Output: Response 405 with ``Allow: POST``.
    """
    return Response(status_code=405, headers={"Allow": "POST"})

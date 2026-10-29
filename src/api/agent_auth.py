
from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from fastapi import HTTPException, Request

from src.api.enrollment_gate import is_loopback_host
from src.core.mcp import token_store, trusted_proxy
from src.core.mcp.caller import TOKEN_ID_PREFIX, AgentCaller

logger = structlog.get_logger()

SESSION_HEADER = "x-carnivore-session"


def _refuse(request: Request, status: int, reason: str, detail: str) -> HTTPException:
    logger.warning(
        "mcp_agent_refused",
        status=status,
        reason=reason,
        session_id=(request.headers.get(SESSION_HEADER) or "")[:64],
    )
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return HTTPException(status_code=status, detail=detail, headers=headers)


def _bearer(request: Request) -> Optional[str]:
    value = request.headers.get("authorization", "")
    return value[7:].strip() if value[:7].lower() == "bearer " else None


async def require_agent(request: Request) -> AgentCaller:
    client = request.client
    if request.scope.get("via_link"):
        raise _refuse(request, 403, "via_link", "loopback only")
    if client is None:
        raise _refuse(request, 403, "not_loopback", "loopback only")
    via_proxy = not is_loopback_host(client.host)
    if via_proxy and not trusted_proxy.is_trusted(client.host):
        raise _refuse(request, 403, "not_loopback", "loopback only")
    if not via_proxy and ("x-forwarded-for" in request.headers or "forwarded" in request.headers):
        raise _refuse(request, 403, "proxied", "proxied requests are refused")
    if "origin" in request.headers:
        raise _refuse(request, 403, "origin_present", "browser origins are refused")

    token = _bearer(request)
    if token_store.is_token(token):
        row = await asyncio.to_thread(token_store.get_store().authenticate, token)
        if row is None:
            raise _refuse(request, 401, "bad_token", "agent credential required")
        if via_proxy:
            logger.info("mcp_agent_proxy_accepted", client_host=client.host, token_name=row["name"])
        ident = f"{TOKEN_ID_PREFIX}{row['id']}"
        return AgentCaller(session_id=ident, tmux_name=ident, current_session_id=ident,
                           token_name=row["name"], scope=row["scope"])
    if via_proxy:
        raise _refuse(request, 403, "proxy_needs_owner_token", "only an owner-minted token is accepted through the proxy")
    session_id = (request.headers.get(SESSION_HEADER) or "").strip()
    manager = request.app.state.session_manager
    if not token or not session_id or not manager.hook_tokens.verify(session_id, token):
        raise _refuse(request, 401, "bad_credential", "agent credential required")
    tmux_name = manager.hook_tokens.name_for(session_id)
    if not tmux_name:
        raise _refuse(request, 401, "unbound_token", "agent credential is not bound to a pane")
    live = manager._registry.registered_ids_for_tmux_name(tmux_name)
    if not live:
        pending = manager._pending_agent_registration.get(session_id)
        if pending is not None and pending[0] == tmux_name:
            try:
                await asyncio.wait_for(pending[1].wait(), timeout=4)
            except asyncio.TimeoutError:
                pass
            if not manager.hook_tokens.verify(session_id, token) or manager.hook_tokens.name_for(session_id) != tmux_name:
                raise _refuse(request, 401, "bad_credential", "agent credential required")
            live = manager._registry.registered_ids_for_tmux_name(tmux_name)
    if not live:
        raise _refuse(request, 401, "session_not_live", "agent session is not live")
    return AgentCaller(
        session_id=session_id, tmux_name=tmux_name, current_session_id=live[0]
    )

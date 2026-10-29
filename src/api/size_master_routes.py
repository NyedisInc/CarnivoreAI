
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api import peer_ws_auth, size_master
from src.api.peer_auth import require_peer_sessions
from src.api.resize_negotiation import get_negotiator
from src.api.ws_connections import connection_manager
from src.core.federation import peer_terminal_proxy
from src.core.hosts.identity import parse_remote_session_id

router = APIRouter()


class SizeMasterClaim(BaseModel):
    """The body of a claim: the browser tab taking the size."""

    client_id: str = Field(..., pattern=size_master.CLIENT_ID_PATTERN.pattern)


class SizeMasterState(BaseModel):
    """Who holds a session's size, as every size-master route answers it."""

    session_id: str
    master: Optional[str] = None
    master_attached: bool = False


def _live_session(request: Request, session_id: str) -> Tuple[Any, str]:
    registry = request.app.state.services.registry
    if getattr(request.state, "peer_grant", None) is not None:
        session_id = peer_ws_auth.local_session_id(registry, session_id)
    if session_id not in registry.sessions:
        raise HTTPException(status_code=404, detail="unknown session")
    return request.app.state.session_manager, session_id


async def _relayed(request: Request, session_id: str, method: str, body: Optional[dict] = None,
                   client_id: Optional[str] = None) -> Optional[JSONResponse]:
    parsed = parse_remote_session_id(session_id)
    if parsed is None or not parsed[0].startswith("peer-") or getattr(request.state, "peer_grant", None) is not None:
        return None
    try:
        status, data = await peer_terminal_proxy.forward_crown(parsed[0], parsed[1], method, session_id, body, client_id)
    except peer_terminal_proxy.PeerUnavailable:
        raise HTTPException(status_code=502, detail="peer_unavailable") from None
    return JSONResponse(data, status_code=status)


@router.get(
    "/sessions/{session_id}/size-master",
    response_model=SizeMasterState,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_size_master(request: Request, session_id: str) -> Dict[str, Any]:
    """Read who holds a session's size.

    Example: GET /api/v1/sessions/ses_1/size-master
      -> {"session_id": "ses_1", "master": null, "master_attached": false}
    """
    relayed = await _relayed(request, session_id, "GET")
    if relayed is not None:
        return relayed
    manager, session_id = _live_session(request, session_id)
    return size_master.state(session_id, get_negotiator(manager))


@router.put(
    "/sessions/{session_id}/size-master",
    response_model=SizeMasterState,
    dependencies=[Depends(require_peer_sessions)],
)
async def claim_size_master(
    request: Request, session_id: str, body: SizeMasterClaim
) -> Dict[str, Any]:
    """Make one browser tab the session's size master (last claim wins).

    Example: PUT /api/v1/sessions/ses_1/size-master {"client_id": "k3x9..."}
    """
    relayed = await _relayed(request, session_id, "PUT", body.model_dump())
    if relayed is not None:
        return relayed
    manager, session_id = _live_session(request, session_id)
    return await size_master.set_master(
        manager, session_id, body.client_id, connection_manager, reason="claim")


@router.delete(
    "/sessions/{session_id}/size-master",
    response_model=SizeMasterState,
    dependencies=[Depends(require_peer_sessions)],
)
async def release_size_master(
    request: Request,
    session_id: str,
    client_id: Optional[str] = Query(None, pattern=size_master.CLIENT_ID_PATTERN.pattern),
) -> Dict[str, Any]:
    """Give a session's size back to smallest-wins.

    Raises: 409 when ``client_id`` is given and does not hold the crown.
    Example: DELETE /api/v1/sessions/ses_1/size-master?client_id=k3x9...
    """
    relayed = await _relayed(request, session_id, "DELETE", client_id=client_id)
    if relayed is not None:
        return relayed
    manager, session_id = _live_session(request, session_id)
    negotiator = get_negotiator(manager)
    holder = negotiator.master(session_id)
    if holder is None:
        return size_master.state(session_id, negotiator)
    if client_id is not None and holder != client_id:
        raise HTTPException(status_code=409, detail="that window does not hold the size")
    return await size_master.set_master(
        manager, session_id, None, connection_manager, reason="release")

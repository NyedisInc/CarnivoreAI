
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.federation_pack_transport_routes import _peer_only
from src.api.peer_auth import Principal, require_peer
from src.core.pack.jobs.types import JobError
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.session_place import host as session_host
from src.core.pack.session_place.types import CAP_SESSION_PLACE
from src.core.pack.session_place.wire import PeerCreateAnswer, PeerCreateBody
from src.api.error_response import refusal_error

router = APIRouter(prefix="/federation/pack/sessions", tags=["federation"])
_require_replica = require_peer("replica")
pack_capabilities.register(CAP_SESSION_PLACE)


@router.post("/create", response_model=PeerCreateAnswer)
async def create(body: PeerCreateBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Start one session in this computer's copy of the project (once per request id). Output: PeerCreateAnswer. Raises 403 pack_restricted, 409, 503."""
    caller = _peer_only(principal)
    try:
        return await session_host.create(request.app, caller, body)
    except JobError as exc:
        raise refusal_error(exc) from exc

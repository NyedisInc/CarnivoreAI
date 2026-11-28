
from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from src.api.federation_routes import TokenResponse
from src.core.federation import mesh_grants, pairing, peer_token
from src.core.pack.machines import capabilities


class FederationMeshRoutesError(ValueError):
    pass


logger = structlog.get_logger()
router = APIRouter(prefix="/federation", tags=["federation"])

_WINDOWS = pairing.KeyedWindows(60, 60.0)
_MAX_BODY = 4096


class MeshTokenRequest(BaseModel):
    """The signed challenge. There is no install id: the transport tag names the peer."""

    model_config = ConfigDict(extra="forbid")

    ts: int
    nonce: str
    signature: str


def _grant_invalid() -> HTTPException:
    return HTTPException(401, {"code": "grant_invalid", "detail": "the challenge was not accepted"})


@router.post("/mesh/token", response_model=TokenResponse)
async def mesh_token(request: Request) -> TokenResponse:
    """Sign a challenge, get a member token. 404 while the switch is off; 401 for any bad challenge, no tag or no pinned session; 429 when too many."""
    if not capabilities.mesh_on():
        raise HTTPException(404, "Not Found")
    tag = request.scope.get("mesh_peer")
    if not isinstance(tag, str) or not tag:
        raise _grant_invalid()
    if not _WINDOWS.hit(tag, time.monotonic()):
        raise HTTPException(429, {"code": "token_rate_limited", "detail": "too many token requests"})
    raw = await request.body()
    try:
        if len(raw) > _MAX_BODY:
            raise FederationMeshRoutesError("too large")
        body = MeshTokenRequest.model_validate_json(raw)
        if len(body.nonce) > 64 or len(body.signature) > 128:
            raise FederationMeshRoutesError("too long")
    except (ValidationError, ValueError):
        raise _grant_invalid() from None
    g = await mesh_grants.current(tag)
    if g is None:
        raise _grant_invalid()
    try:
        peer_token.verify_challenge(g, g.issuer, body.ts, body.nonce, body.signature,
                                    prefix=peer_token.MESH_CHALLENGE_PREFIX)
    except peer_token.PeerTokenError:
        logger.info("mesh_token_refused", peer=tag[:8])
        raise _grant_invalid() from None
    token, ttl = peer_token.mint(g, g.issuer, kind=peer_token.MESH_KIND)
    return TokenResponse(token=token, expires_in=ttl, install_id=g.issuer)

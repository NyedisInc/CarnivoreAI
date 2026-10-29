
from __future__ import annotations

import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.peer_auth import Principal, require_peer
from src.core.notifications.destinations.service import get_service
from src.core.notifications.sync import secrets_sync, wire

router = APIRouter(prefix="/federation/notify-sync", tags=["federation"])

_NO_STORE = {"Cache-Control": "no-store"}
_require_settings = require_peer("settings")
_secret_limiter = secrets_sync.RateLimiter()


class ExchangeBody(BaseModel):
    """One bucket of an exchange (see ``wire``). ``entries`` is validated entry by entry, never trusted."""

    model_config = ConfigDict(extra="forbid")

    v: int
    digest: str = Field(max_length=64)
    buckets: int = Field(ge=1, le=wire.MAX_BUCKETS)
    bucket: int = Field(ge=0)
    entries: Dict[str, Any] = Field(default_factory=dict)


class SecretsBody(BaseModel):
    """The destinations whose secret bundles the peer wants."""

    model_config = ConfigDict(extra="forbid")

    dest_ids: List[str] = Field(max_length=secrets_sync.MAX_IDS_PER_REQUEST)


def _peer_only(principal: Principal) -> Principal:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer syncs settings"})
    return principal


@router.post("/exchange")
async def exchange(body: ExchangeBody, request: Request, principal: Principal = Depends(_require_settings)) -> JSONResponse:
    """Merge the caller's bucket of its global map and answer with this computer's newer entries (or no_change)."""
    _peer_only(principal)
    service = get_service(request.app.state)
    try:
        answer = await wire.serve_exchange(service.docs, service.secrets, body.model_dump(), time.time())
    except ValueError:
        raise HTTPException(422, {"code": "bad_exchange", "detail": "the exchange body is not valid"}) from None
    except OSError:
        raise HTTPException(503, {"code": "write_failed", "detail": "the settings could not be saved"}) from None
    return JSONResponse(answer, headers=_NO_STORE)


@router.post("/secrets")
async def secrets(body: SecretsBody, request: Request, principal: Principal = Depends(_require_settings)) -> JSONResponse:
    """Serve the Keychain secret bundles of the named GLOBAL destinations. 429 past 30 requests a minute per grant."""
    grant = _peer_only(principal).grant
    assert grant is not None
    if not _secret_limiter.allow(grant.grant_id):
        raise HTTPException(429, {"code": "rate_limited", "detail": "too many secret requests"},
                            headers={"Retry-After": "60", **_NO_STORE})
    service = get_service(request.app.state)
    answer = await secrets_sync.serve(service.docs, service.secrets, list(body.dest_ids))
    return JSONResponse(answer, headers=_NO_STORE)

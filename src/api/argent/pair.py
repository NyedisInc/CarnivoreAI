
from __future__ import annotations

import asyncio
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.api.peer_auth import Principal, require_peer
from src.core.argent import pair_sync
from src.core.argent.pair_credential import CAP_CREDENTIAL, CredentialBody, PairRefused
from src.core.argent.pair_sync import CAP_SWITCH, SwitchBody
from src.core.pack.machines import capabilities, restrictions as restrictions_mod

logger = structlog.get_logger()
federation_router = APIRouter(prefix="/federation/argent", tags=["federation"])
router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])
capabilities.register(CAP_SWITCH)
capabilities.register(CAP_CREDENTIAL)
_require_machine = require_peer("machine")
_require_credentials = require_peer("credentials")
_NO_STORE = {"Cache-Control": "no-store"}


def _sync() -> pair_sync.PairSync:
    sync = pair_sync.get()
    if sync is None:
        raise HTTPException(503, {"code": "pair_not_ready", "detail": "the federation layer is not running"})
    return sync


def _sender(principal: Principal) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer calls this"})
    return principal.grant.peer_install_id


async def _body(request: Request, model: Any) -> Any:
    try:
        return model.model_validate(await request.json())
    except (ValidationError, ValueError):
        raise HTTPException(422, {"code": "bad_pair_body", "detail": "the body is not valid"}) from None


@federation_router.post("/switch")
async def receive_switch(request: Request, principal: Principal = Depends(_require_machine)) -> JSONResponse:
    """Apply a listed computer's switch value (last write wins on a logical clock) and start this computer's rollout when its owner started one there."""
    sender = _sender(principal)
    body = await _body(request, SwitchBody)
    try:
        out = await _sync().receive_switch(sender, body, request.app.state)
    except PairRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": "the switch value was not applied"}) from None
    return JSONResponse(out, headers=_NO_STORE)


@federation_router.post("/credential")
async def receive_credential(request: Request, principal: Principal = Depends(_require_credentials),
                             _allowed: None = Depends(restrictions_mod.require_peer_allowed(
                                 restrictions_mod.ACTION_RECEIVE_CREDENTIALS))) -> JSONResponse:
    """Store the pushed Argent access token (keychain by stdin) and CA certificate. Refused while this computer holds a live login of its own."""
    sender = _sender(principal)
    body = await _body(request, CredentialBody)
    try:
        expiry = await _sync().receive_credential(sender, body)
    except PairRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": "the credential was not stored"}) from None
    return JSONResponse({"ok": True, "expires_at": expiry}, headers=_NO_STORE)


@federation_router.post("/credential/request")
async def request_credential(principal: Principal = Depends(_require_machine)) -> JSONResponse:
    """A member whose relayed token got a 401 asks for a fresh delegate. Scope ``machine`` (the OWNER's own ``may_receive_credentials`` is not involved here); an unlisted
    or contained sender gets nothing, and the approval and ``may_receive_credentials`` gates of the member run in the sender (``push``)."""
    await _sync().credentials_requested(_sender(principal))
    return JSONResponse({"ok": True}, headers=_NO_STORE)


@router.get("/pair")
async def get_pair() -> Dict[str, Any]:
    """Every listed computer's switch and credential relay state. Example: GET /api/v1/argent/pair -> {"clock": 1, "computers": [{"label": "nostromo", ...}]}"""
    return await run_in_threadpool(_sync().view)

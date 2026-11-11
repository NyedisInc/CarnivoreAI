
from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.api.argent.pair import _NO_STORE, _sender, _sync
from src.api.auth import require_auth
from src.api.peer_auth import Principal, require_peer
from src.core.argent import gateway_reach, poll_relay
from src.core.argent.pair_credential import PairRefused
from src.core.argent.poll_relay import CAP_POLL, PollBody
from src.core.hosts.registry import HostRegistry
from src.core.hosts.store import KEY_RE
from src.core.pack.machines import capabilities

logger = structlog.get_logger()
federation_router = APIRouter(prefix="/federation/argent", tags=["federation"])
router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])
capabilities.register(CAP_POLL)
_require_machine = require_peer("machine")


def _registry(request: Request) -> HostRegistry:
    manager = getattr(request.app.state, "session_manager", None)
    if manager is None:
        raise HTTPException(503, {"code": "hosts_not_ready", "detail": "the session manager is not running"})
    return manager.hosts


def _reach() -> gateway_reach.Reach:
    reach = gateway_reach.get()
    if reach is None:
        raise HTTPException(409, {"code": "feature_off", "detail": "the argent feature is off"})
    return reach


@router.get("/reach")
async def get_reach() -> Dict[str, Any]:
    """Every measured computer's gateway reach and the relayed poll results. Example: GET /api/v1/argent/reach -> {"computers": {"studio": {"state": "carried", ...}}}"""
    reach = gateway_reach.get()
    return {"computers": reach.snapshot() if reach is not None else {}, "relayed": poll_relay.relayed()}


@router.post("/reach/{host_key}/check")
async def check_reach(host_key: str, request: Request) -> Dict[str, Any]:
    """Probe one ssh computer from itself now; carry the gateway to it only when it cannot reach it. Example: POST /api/v1/argent/reach/studio/check"""
    reach = _reach()
    registry = _registry(request)
    if KEY_RE.fullmatch(host_key) is None or host_key not in registry.connected():
        raise HTTPException(404, {"code": "computer_not_connected", "detail": "that computer is not connected over ssh"})
    state = await reach.ensure(host_key, force=True)
    return state.as_public(host_key, registry.label(host_key))


@federation_router.post("/poll")
async def receive_poll(request: Request, principal: Principal = Depends(_require_machine)) -> JSONResponse:
    """Store a listed computer's poll results (read only). Refused 409 when this computer polls Argent itself or the feature is off."""
    sender = _sender(principal)
    try:
        body = PollBody.model_validate(await request.json())
    except (ValidationError, ValueError):
        raise HTTPException(422, {"code": "bad_pair_body", "detail": "the body is not valid"}) from None
    sync = _sync()
    try:
        poll_relay.receive(sender, body, listed=sync.is_listed)
    except PairRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": "the poll results were not stored"}) from None
    return JSONResponse({"ok": True}, headers=_NO_STORE)

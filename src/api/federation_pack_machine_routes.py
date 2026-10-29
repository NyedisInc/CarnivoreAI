
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.peer_auth import Principal, require_peer
from src.core.pack.machines import capabilities, restrictions as restrictions_mod, runtime

router = APIRouter(prefix="/federation/pack", tags=["federation"])
capabilities.register(capabilities.CAP_MACHINE, capabilities.CAP_RESERVE, capabilities.CAP_RESTRICTIONS,
                      capabilities.CAP_SETTINGS_SIGNED)
_require_machine = require_peer("machine")


class ExchangeBody(BaseModel):
    """The caller's own snapshot and its copy of the Pack settings document with its signature (validated, never trusted)."""

    model_config = ConfigDict(extra="forbid")

    snapshot: Dict[str, Any]
    settings: Optional[Dict[str, Any]] = None
    settings_sig: Optional[Dict[str, Any]] = None
    want_agents: bool = False


class PatchBody(BaseModel):
    """A partial reserve or restrictions document; the receiver validates every field."""

    model_config = ConfigDict(extra="forbid")

    patch: Dict[str, Any] = Field(default_factory=dict)


def _peer(principal: Principal) -> Any:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer calls this"})
    return principal.grant


def _wired() -> runtime.Wiring:
    wired = runtime.wiring()
    if wired is None:
        raise HTTPException(503, {"code": "pack_unavailable", "detail": "the Pack machine layer is not running"})
    return wired


@router.post("/exchange")
async def exchange_snapshots(body: ExchangeBody, principal: Principal = Depends(_require_machine)) -> Dict[str, Any]:
    grant = _peer(principal)
    try:
        return await _wired().runtime.serve_exchange(grant.peer_install_id, grant.label, body.model_dump())
    except ValueError:
        raise HTTPException(403, {"code": "snapshot_identity", "detail": "a snapshot is only accepted from the machine it describes"}) from None


@router.put("/reserve")
async def put_reserve(body: PatchBody, principal: Principal = Depends(_require_machine)) -> Dict[str, Any]:
    _peer(principal)
    wired = _wired()
    try:
        cfg = await asyncio.to_thread(wired.runtime.set_reserve, body.patch)
    except ValueError as exc:
        raise HTTPException(422, {"code": "reserve_invalid", "detail": " ".join(str(exc).split())[:300]}) from None
    return {"reserve": cfg.model_dump()}


@router.put("/restrictions/tighten")
async def put_tighten(body: PatchBody, principal: Principal = Depends(_require_machine)) -> Dict[str, Any]:
    _peer(principal)
    wired = _wired()
    try:
        new = await asyncio.to_thread(wired.runtime.set_restrictions, body.patch, from_peer=True)
    except ValueError as exc:
        raise HTTPException(422, {"code": "restrictions_invalid", "detail": " ".join(str(exc).split())[:300]}) from None
    except PermissionError as exc:
        raise restrictions_mod.refusal(f"loosen_refused:{exc}") from None
    await asyncio.to_thread(wired.sync_scopes)
    return {"restrictions": new.model_dump()}

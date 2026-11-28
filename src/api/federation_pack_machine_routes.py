
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.api.peer_auth import Principal, require_peer
from src.core.pack.machines import capabilities, restrictions as restrictions_mod, runtime
from src.api.error_response import api_error

router = APIRouter(prefix="/federation/pack", tags=["federation"])
capabilities.register(capabilities.CAP_MACHINE, capabilities.CAP_RESERVE, capabilities.CAP_RESTRICTIONS,
                      capabilities.CAP_SETTINGS_SIGNED, capabilities.CAP_ROSTER)
_require_machine = require_peer("machine")


class ExchangeBody(BaseModel):
    """The caller's own snapshot and its copy of the Pack settings document with its signature (validated, never trusted)."""

    model_config = ConfigDict(extra="forbid")

    snapshot: Dict[str, Any]
    settings: Optional[Dict[str, Any]] = None
    settings_sig: Optional[Dict[str, Any]] = None
    roster: Optional[Dict[str, Any]] = None
    roster_v2: Optional[Dict[str, Any]] = None
    want_agents: bool = False


class PatchBody(BaseModel):
    """A partial reserve or restrictions document; the receiver validates every field."""

    model_config = ConfigDict(extra="forbid")

    patch: Dict[str, Any] = Field(default_factory=dict)


class LabelsBody(BaseModel):
    """The whole label list for this computer; the receiver validates every label."""

    model_config = ConfigDict(extra="forbid")

    labels: List[str] = Field(max_length=16)


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
    """Take the caller's snapshot and settings document, answer with this machine's own (the loop guard: own data only)."""
    grant = _peer(principal)
    try:
        return await _wired().runtime.serve_exchange(grant.peer_install_id, grant.label, body.model_dump(exclude_unset=True))
    except ValueError:
        raise HTTPException(403, {"code": "snapshot_identity", "detail": "a snapshot is only accepted from the machine it describes"}) from None


@router.put("/reserve")
async def put_reserve(body: PatchBody, principal: Principal = Depends(_require_machine)) -> Dict[str, Any]:
    """Edit this machine's reserve on a peer's behalf: a comfort setting, so it may be loosened remotely (F22)."""
    grant = _peer(principal)
    wired = _wired()
    if capabilities.mesh_on():
        alpha = await asyncio.to_thread(wired.runtime.content_alpha)
        if alpha is None or grant.peer_install_id != alpha:
            raise HTTPException(403, {"code": "pack_reserve_alpha_only", "detail": "the reserve changes only at the alpha or on this computer"})
    try:
        cfg = await asyncio.to_thread(wired.runtime.set_reserve, body.patch)
    except ValueError as exc:
        raise HTTPException(422, {"code": "reserve_invalid", "detail": " ".join(str(exc).split())[:300]}) from None
    return {"reserve": cfg.model_dump()}


@router.put("/restrictions/tighten")
async def put_tighten(body: PatchBody, principal: Principal = Depends(_require_machine)) -> Dict[str, Any]:
    """Narrow this machine's restrictions on a peer's behalf. A patch that loosens anything is refused 403
    ``pack_restricted``: only the owner, on this machine, loosens (F22)."""
    _peer(principal)
    wired = _wired()
    try:
        new = await asyncio.to_thread(wired.runtime.set_restrictions, body.patch, from_peer=True)
    except ValueError as exc:
        raise api_error(422, "restrictions_invalid", None, error_type=type(exc).__name__) from None
    except PermissionError as exc:
        raise restrictions_mod.refusal(f"loosen_refused:{exc}") from None
    await asyncio.to_thread(wired.sync_scopes)
    return {"restrictions": new.model_dump()}


@router.post("/rescan")
async def post_rescan(principal: Principal = Depends(_require_machine)) -> Dict[str, Any]:
    """Re-probe this computer's toolchain and abilities on a peer's behalf (at most one abilities probe per 60 s; ``fresh`` says if it ran)."""
    _peer(principal)
    return await asyncio.to_thread(_wired().rescan_self)


@router.put("/labels")
async def put_labels(body: LabelsBody, principal: Principal = Depends(_require_machine)) -> Dict[str, Any]:
    """Replace this computer's labels on a peer's behalf: a placement hint, so it may be edited remotely like the reserve."""
    _peer(principal)
    try:
        labels = await asyncio.to_thread(_wired().set_labels, body.labels)
    except ValueError as exc:
        raise api_error(422, "labels_invalid", exc) from exc
    except OSError as exc:
        raise api_error(500, "config_unwritable", exc) from exc
    return {"labels": labels}

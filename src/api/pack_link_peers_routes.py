
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from src.api import pack_machines_routes
from src.api.auth import require_auth, security
from src.api.error_response import api_error
from src.core.api_keys.store import is_api_key
from src.core.pack.machines import capabilities

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/pack/link-peers", tags=["pack-machines"])


class LinkPeersBody(BaseModel):
    """The body of ``PUT /pack/link-peers``: one computer (install id, label or ``self``) and its new switch value."""

    model_config = ConfigDict(extra="forbid")
    machine: str = Field(min_length=1, max_length=128)
    on: StrictBool


async def _mesh_route() -> None:
    if not capabilities.mesh_on():
        raise HTTPException(404, "Not Found")


async def _owner_login(request: Request, _auth: bool = Depends(require_auth), credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> None:
    if (credentials is not None and is_api_key(credentials.credentials)) or request.scope.get("via_peer_link") or request.scope.get("mesh_peer"):
        raise api_error(403, "link_peers_owner_only")


@router.put("", dependencies=[Depends(_mesh_route), Depends(_owner_login)])
async def put_link_peers(body: LinkPeersBody) -> Dict[str, Any]:
    """Turn one member's link switch on or off in the signed computer list (alpha only; the next list reaches every member).

    Raises 409 ``link_peers_not_alpha`` / ``link_peers_frozen``, 404 ``machine_unknown``, 422 ``link_peers_alpha`` / ``link_peers_unknown``, 503 ``link_peers_not_issued`` (a ValueError from the planner answers 422 ``roster_invalid``).
    Example: PUT /api/v1/pack/link-peers {"machine": "host-b", "on": false} -> {"machine": "<install id>", "on": false, "changed": "bump:authority", "generation": 7}
    """
    wired = pack_machines_routes._wired()
    custody = wired.runtime.custody
    master, interim = await asyncio.to_thread(lambda: (custody.settings().master_install_id, custody.interim()))
    if master != wired.runtime.install_id:
        raise api_error(409, "link_peers_not_alpha", extra={"alpha": master})
    if interim:
        raise api_error(409, "link_peers_frozen")
    peers = await asyncio.to_thread(wired.peers)
    target = pack_machines_routes._resolve(wired, body.machine, peers)
    if target == wired.runtime.install_id:
        raise api_error(422, "link_peers_alpha")
    lst = await asyncio.to_thread(lambda: custody.roster_v2() or custody.roster())
    if lst is None or lst.entry(target) is None:
        raise api_error(422, "link_peers_unknown")
    result = await pack_machines_routes._roster_edit(wired, peers, link_peers={target: body.on})
    v2_now = await asyncio.to_thread(custody.roster_v2)
    entry = v2_now.entry(target) if v2_now is not None else None
    if entry is None or entry.link_peers != body.on:
        raise api_error(503, "link_peers_not_issued")
    logger.info("pack_link_peers_set", machine=target[:8], on=body.on, generation=v2_now.generation)
    return {"machine": target, "on": body.on, "changed": result["changed"], "generation": v2_now.generation}

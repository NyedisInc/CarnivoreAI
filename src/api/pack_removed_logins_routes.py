
from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from src.api.auth import require_auth, security
from src.api.error_response import api_error
from src.api import peer_auth
from src.core.api_keys.store import is_api_key
from src.core.pack.machines import capabilities
from src.core.pack.relay import removed_copies, rotation
from src.core.provider_ledger import poller

router = APIRouter(prefix="/pack/removed-logins", tags=["pack-relay"])


async def mesh_route() -> None:
    if not capabilities.mesh_on():
        raise HTTPException(404, "Not Found")


def owner_only(code: str) -> Callable[..., Awaitable[None]]:
    async def _owner_login(request: Request, _auth: bool = Depends(require_auth),
                           credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> None:
        if (credentials is not None and is_api_key(credentials.credentials)) or request.scope.get("via_peer_link") or request.scope.get("mesh_peer"):
            raise api_error(403, code)
    return _owner_login


@router.get("", dependencies=[Depends(mesh_route), Depends(owner_only("removed_logins_owner_only"))])
async def removed_logins() -> Dict[str, Any]:
    """Per removed computer, the copies sent to it with ``dead_now`` (a 204 confirmed), ``dies_by`` (stored expiry), ``expired`` or ``expiry_unknown``.

    Example: GET /api/v1/pack/removed-logins -> {"computers": [{"install_id", "removed_at", "state", "copies": [...]}], "argent_known": true, "not_tracked": ["github"]}"""
    from src.core.argent import pair_sync

    pair = pair_sync.PAIR
    usage = poller.snapshot().accounts

    def read() -> Dict[str, Any]:
        seen = rotation.seen_from(lambda: peer_auth.open_db(), usage)
        return removed_copies.build(lambda: peer_auth.open_db(), None if pair is None else pair.credentials.delegate_copies, int(time.time() * 1000), seen)

    try:
        return await asyncio.to_thread(read)
    except (sqlite3.Error, OSError) as exc:
        raise api_error(503, "removed_logins_unavailable", exc) from exc

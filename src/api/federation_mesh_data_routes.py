
from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.api.capped_reads import read_capped_body
from src.api.peer_auth import Principal, require_peer
from src.core.computers import direction
from src.core.notifications.sync.secrets_sync import RateLimiter
from src.core.pack.machines import capabilities, exchange
from src.core.pack.meshdata import gossip, hlc, wire


class FederationMeshDataRoutesError(ValueError):
    pass


MAX_BODY_BYTES = 64 * 1024
SYNC_RATE_LIMIT = 1200
_limiter = RateLimiter(limit=SYNC_RATE_LIMIT, window=60.0)


def _switch() -> None:
    if not capabilities.mesh_on():
        raise HTTPException(404, "Not Found")


router = APIRouter(prefix="/federation/pack/mesh", tags=["federation"], dependencies=[Depends(_switch)])
_require_machine = require_peer("machine")


@router.post("/sync")
async def post_sync(request: Request, principal: Principal = Depends(_require_machine)) -> JSONResponse:
    """Keep the caller's verified records of one bucket and answer with the newer ones this computer holds.

    Output: ``wire.handle_sync``'s answer. Raises: 403 ``peer_token_required`` or one way, 429 ``rate_limited``, 413 over 64 KiB, 422 malformed body, 503 ``meshdata_unavailable``.
    """
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer calls this"})
    caller = principal.grant.peer_install_id
    if not _limiter.allow(caller):
        return JSONResponse({"code": "rate_limited"}, status_code=429, headers={"Cache-Control": "no-store"})
    runtime, service = exchange.RUNTIME, gossip.ACTIVE
    gen = service.store.generation if service is not None else None
    lst = await asyncio.to_thread(runtime.held_list) if runtime is not None else None
    if direction.contained(caller) or direction.listed_one_way(lst, caller):
        raise HTTPException(403, {"code": direction.REFUSAL_CODE, "detail": "this computer shares nothing with a one-way computer"})
    if service is None:
        raise HTTPException(503, {"code": "meshdata_unavailable"})
    raw = await read_capped_body(request, MAX_BODY_BYTES, "mesh sync")
    try:
        body: Any = json.loads(raw)
        if not isinstance(body, dict):
            raise FederationMeshDataRoutesError("body is not an object")
        answer, accepted = await asyncio.to_thread(wire.handle_sync, service.store, body, caller, lst, hlc.wall_ms(), gen)
    except (ValueError, RecursionError):
        raise HTTPException(422, {"code": "mesh_sync_body"}) from None
    except sqlite3.Error:
        raise HTTPException(503, {"code": "meshdata_unavailable"}) from None
    if accepted:
        gossip.wake()
    return JSONResponse(answer, headers={"Cache-Control": "no-store"})

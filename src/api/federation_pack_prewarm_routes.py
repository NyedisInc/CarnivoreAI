
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from src.api.federation_pack_jobs_routes import _call, is_member
from src.api.peer_auth import Principal, require_peer
from src.core.pack.jobs import prewarm as prewarm_mod

router = APIRouter(prefix="/federation/pack/jobs", tags=["federation"])
_require_replica = require_peer("replica")


@router.post("/prewarm")
async def prewarm(body: prewarm_mod.PrewarmBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Warm one folder for the caller's project when this computer is idle. Output: {ok: true} or {ok: false, reason}. Raises 403, 409 project_not_here."""
    return await _call(request, principal, lambda h, c: prewarm_mod.prewarm(h, c, body, member=is_member(principal)))

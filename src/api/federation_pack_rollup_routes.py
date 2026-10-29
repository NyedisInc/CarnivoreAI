
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.peer_auth import Principal, require_peer
from src.core.computers import direction
from src.core.pack.machines import capabilities
from src.core.stats import rollup

router = APIRouter(prefix="/federation/pack", tags=["federation"])
capabilities.register(capabilities.CAP_PIPELINE_ROLLUP)
_require_machine = require_peer("machine")


@router.get("/rollup")
async def get_rollup(
    request: Request,
    since_rev: int = Query(0, ge=0, description="the last revision the caller finished pulling"),
    until_rev: Optional[int] = Query(None, ge=0, description="the cut the first page pinned (echo it on later pages)"),
    cursor: Optional[str] = Query(None, max_length=2048, description="next_cursor of the previous page"),
    max_bytes: int = Query(rollup.PAGE_BYTES, ge=4096, le=rollup.MAX_PAGE_BYTES),
    principal: Principal = Depends(_require_machine),
) -> Dict[str, Any]:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer calls this"})
    if direction.contained(principal.grant.peer_install_id):
        raise HTTPException(403, {"code": direction.REFUSAL_CODE, "detail": "this computer shares nothing with a one-way computer"})
    store = getattr(request.app.state, "stats_store", None)
    if store is None:
        raise HTTPException(503, {"code": "stats_unavailable"})
    try:
        return await asyncio.to_thread(rollup.serve, store, since_revision=since_rev, until_revision=until_rev,
                                       cursor=cursor, max_bytes=max_bytes)
    except ValueError:
        raise HTTPException(422, {"code": "rollup_cursor", "detail": "the page cursor is not one this computer issued"}) from None

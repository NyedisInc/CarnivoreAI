
from __future__ import annotations

import asyncio
from typing import Any, Dict, FrozenSet, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from src.api import peer_auth
from src.api.peer_auth import Principal, require_peer
from src.core.computers import direction
from src.core.federation import peer_links
from src.core.federation.mesh_grants import MeshGrant
from src.core.notifications.sync.secrets_sync import RateLimiter
from src.core.pack.machines import capabilities, exchange
from src.core.pack.machines.roster_v2 import RosterV2
from src.core.pack.meshdata import gossip
from src.core.pack.rollup_import import relay_export
from src.core.stats import rollup

router = APIRouter(prefix="/federation/pack", tags=["federation"])
capabilities.register(capabilities.CAP_PIPELINE_ROLLUP, capabilities.CAP_ROLLUP_RELAY, capabilities.CAP_ROLLUP_V2)
_require_machine = require_peer("machine")
ROLLUP_MEMBER_RATE_LIMIT = 120
_member_limiter = RateLimiter(limit=ROLLUP_MEMBER_RATE_LIMIT, window=60.0)


def _withheld_from(caller: str) -> FrozenSet[str]:
    active, runtime = gossip.ACTIVE, exchange.RUNTIME
    if active is None or runtime is None:
        return frozenset()
    lst = runtime.held_list()
    return active.store.withholding(lst, caller) if isinstance(lst, RosterV2) else frozenset()


def _serve(store: Any, caller: str, signing: Optional[Any], **page: Any) -> Dict[str, Any]:
    withheld = _withheld_from(caller) if capabilities.mesh_on() and page.get("stream") == "relay" else frozenset()
    return relay_export.serve_stream(store, peer_auth.open_db, caller=caller, signing=signing, withheld=withheld, **page)


def _signing_for(grant: Any) -> Optional[Any]:
    if not capabilities.mesh_on():
        return None
    links = peer_links.LINKS
    advertises = links is not None and capabilities.has(links.capabilities(grant.peer_install_id), capabilities.CAP_MESH)
    if not (isinstance(grant, MeshGrant) or advertises):
        return None
    runtime = exchange.RUNTIME
    signing = runtime.custody.signing if runtime is not None else None
    if signing is None:
        raise HTTPException(503, {"code": "stats_unavailable"})
    return signing


@router.get("/rollup")
async def get_rollup(
    request: Request,
    since_rev: int = Query(0, ge=0, description="the last revision the caller finished pulling"),
    until_rev: Optional[int] = Query(None, ge=0, description="the cut the first page pinned (echo it on later pages)"),
    cursor: Optional[str] = Query(None, max_length=2048, description="next_cursor of the previous page"),
    max_bytes: int = Query(rollup.PAGE_BYTES, ge=4096, le=rollup.MAX_PAGE_BYTES),
    stream: Optional[Literal["own", "relay"]] = Query(None, description="own or relay (pack.rollup_relay); absent answers today's own rows"),
    principal: Principal = Depends(_require_machine),
    v2: bool = Query(False, description="include rollup v2 supplement on page 1 (pack.rollup_v2)"),
) -> Dict[str, Any]:
    """One page of this computer's own hour-grain usage and counters. Output: ``relay_export.serve_stream``'s dict (``rollup.serve``'s when ``stream`` is absent) (``available``,
    ``revision``, ``complete``, ``next_cursor``, ``groups``...). Raises: 403, 422 ``rollup_cursor``, 429 ``rate_limited`` (a member caller over ``ROLLUP_MEMBER_RATE_LIMIT``), 503 ``stats_unavailable``."""
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer calls this"})
    if isinstance(principal.grant, MeshGrant) and not _member_limiter.allow(principal.grant.peer_install_id):
        return JSONResponse({"code": "rate_limited"}, status_code=429, headers={"Cache-Control": "no-store"})
    if direction.contained(principal.grant.peer_install_id):
        raise HTTPException(403, {"code": direction.REFUSAL_CODE, "detail": "this computer shares nothing with a one-way computer"})
    store = getattr(request.app.state, "stats_store", None)
    if store is None:
        raise HTTPException(503, {"code": "stats_unavailable"})
    try:
        return await asyncio.to_thread(_serve, store, principal.grant.peer_install_id, _signing_for(principal.grant), stream=stream, since_revision=since_rev,
                                       until_revision=until_rev, cursor=cursor, max_bytes=max_bytes, include_v2=v2)
    except ValueError:
        raise HTTPException(422, {"code": "rollup_cursor", "detail": "the page cursor is not one this computer issued"}) from None

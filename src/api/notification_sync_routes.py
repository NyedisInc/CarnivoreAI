
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_auth
from src.core.notifications.destinations.service import get_service
from src.core.notifications.sync import runtime, status as st
from src.core.notifications.sync.manager import SyncManager

router = APIRouter(prefix="/notifications/sync", tags=["notifications"], dependencies=[Depends(require_auth)])


class PeerSwitchBody(BaseModel):
    """``PUT /peers/{key}``: sync with this peer on or off."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


def _manager(request: Request) -> SyncManager:
    manager = runtime.current(request.app.state)
    if manager is None:
        raise HTTPException(503, {"error": "sync_unavailable"})
    return manager


async def sync_summary(app_state: Any) -> Dict[str, Any]:
    manager = runtime.current(app_state)
    if manager is None:
        return {"available": False, "peers": []}
    doc = await asyncio.to_thread(manager.store.snapshot)
    body = st.summarise(await manager.gateway.roster(), doc, manager.status)
    return {"available": True, **body}


@router.get("")
async def get_sync(request: Request) -> Dict[str, Any]:
    """Per peer: label, on or off, protocol (ok, older or unknown), link state, last exchange time and result."""
    return await sync_summary(request.app.state)


@router.put("/peers/{key}")
async def put_peer(key: str, body: PeerSwitchBody, request: Request) -> Dict[str, Any]:
    """Switch sync with one peer on or off (local only, never synced). 404 for an unknown peer key."""
    manager = _manager(request)
    peer = next((p for p in await manager.gateway.roster() if p.key == key), None)
    if peer is None:
        raise HTTPException(404, {"error": "unknown_peer"})
    service = get_service(request.app.state)
    try:
        await asyncio.to_thread(service.docs.update, lambda doc, me: st.with_enabled(doc, peer.install_id, body.enabled))
    except OSError:
        raise HTTPException(503, {"error": "write_failed"}) from None
    manager.request_sync()
    return await sync_summary(request.app.state)


@router.post("/now")
async def sync_now(request: Request) -> Dict[str, bool]:
    """Ask for a sync pass with every peer now; it runs in the background and this returns at once."""
    _manager(request).request_sync()
    return {"started": True}

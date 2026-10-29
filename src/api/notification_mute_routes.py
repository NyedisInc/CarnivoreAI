
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_auth
from src.core.notifications.destinations.service import get_service
from src.core.notifications.settings_doc import mutes

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


class MuteBody(BaseModel):
    """``PUT /mutes``: mute or unmute one type here or everywhere."""

    model_config = ConfigDict(extra="forbid")

    type_id: str
    scope: str
    muted: bool
    device: Optional[str] = None
    label: Optional[str] = None


def request_device(request: Request, claimed: Optional[str]) -> Optional[str]:
    link = request.scope.get("link_device") if request.scope.get("via_link") else None
    try:
        if isinstance(link, str) and link:
            return mutes.link_device_key(link)
        return mutes.check_device(claimed) if claimed else None
    except ValueError as exc:
        raise HTTPException(422, {"error": "bad_device"}) from exc


@router.get("/mutes")
async def get_mutes(request: Request, device: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    """Every mute, plus the asking device's own mute-here list. Example: GET /api/v1/notifications/mutes?device=b_..."""
    me = request_device(request, device)
    doc = await asyncio.to_thread(get_service(request.app.state).docs.snapshot)
    return mutes.view(doc, me)


@router.put("/mutes")
async def put_mute(body: MuteBody, request: Request) -> Dict[str, Any]:
    """Mute or unmute ``type_id``. 422 ``unknown_type``, ``bad_scope`` or ``bad_device`` (here needs a device).

    Example: PUT /api/v1/notifications/mutes {"type_id": "session.finished", "scope": "everywhere", "muted": true}
    """
    if body.scope not in mutes.SCOPES:
        raise HTTPException(422, {"error": "bad_scope"})
    me = request_device(request, body.device)
    if body.scope == mutes.SCOPE_HERE and me is None:
        raise HTTPException(422, {"error": "bad_device"})
    service = get_service(request.app.state)
    try:
        doc = await asyncio.to_thread(mutes.set_mute, service.docs, body.type_id, body.scope, body.muted,
                                      device=me, label=body.label or "")
    except ValueError as exc:
        raise HTTPException(422, {"error": "unknown_type"}) from exc
    return mutes.view(doc, me)

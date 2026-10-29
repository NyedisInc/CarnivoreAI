
from __future__ import annotations

import asyncio
from typing import Any, List

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.models import SessionInfo

router = APIRouter(tags=["sessions"])


async def companion_infos(app_state: Any) -> List[SessionInfo]:
    manager = getattr(app_state, "session_manager", None)
    registry = getattr(manager, "_registry", None)
    if registry is None:
        return []
    ids = [sid for sid in list(registry.sessions) if registry.is_hidden(sid)]
    if not ids:
        return []
    status_map = await asyncio.to_thread(manager._status_map_for_listing)
    owned_db = await asyncio.to_thread(manager._owned.instances_from_db)
    infos = [manager._session_info_for(sid, status_map=status_map, owned_db=owned_db) for sid in ids]
    return [info for info in infos if info is not None]


@router.get("/sessions/companions", response_model=List[SessionInfo], dependencies=[Depends(require_auth)])
async def list_companions(request: Request) -> List[SessionInfo]:
    if getattr(request.state, "peer_grant", None) is not None:
        return []
    return await companion_infos(request.app.state)

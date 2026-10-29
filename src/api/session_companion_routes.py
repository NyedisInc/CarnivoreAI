
from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.models import SessionInfo

router = APIRouter(tags=["sessions"])


async def companion_infos(app_state: Any) -> List[SessionInfo]:
    manager = getattr(app_state, "session_manager", None)
    if manager is None or getattr(manager, "_registry", None) is None:
        return []
    return await manager.companion_infos()


@router.get("/sessions/companions", response_model=List[SessionInfo], dependencies=[Depends(require_auth)])
async def list_companions(request: Request) -> List[SessionInfo]:
    """The owner's companion shells (the drawer's TERMINALS band); a paired computer gets an empty list.

    Example: GET /sessions/companions  # [] for a peer, one SessionInfo per live companion for the owner
    """
    if getattr(request.state, "peer_grant", None) is not None:
        return []
    return await companion_infos(request.app.state)

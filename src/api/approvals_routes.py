
from __future__ import annotations

import asyncio
from contextlib import closing

import structlog
from fastapi import APIRouter, Depends, Request

from src.api import peer_auth
from src.api.peer_auth import Principal, require_peer_sessions
from src.core.approvals import peer_items
from src.core.approvals.bounds import valid_items
from src.core.db import get_meta
from src.core.db_models import META_INSTALL_ID
from src.models.dialogs import ApprovalsResponse

logger = structlog.get_logger()
router = APIRouter()


def _install_id() -> str | None:
    with closing(peer_auth.open_db()) as conn:
        return get_meta(conn, META_INSTALL_ID)


@router.get("/approvals", response_model=ApprovalsResponse)
async def list_approvals(request: Request,
                         principal: Principal = Depends(require_peer_sessions)) -> ApprovalsResponse:
    """Open approvals and the version the ``approvals`` event announces.

    Output: ApprovalsResponse. ``version`` is read AFTER the items are gathered so an event that
    lands meanwhile only ever makes the client refetch once more.
    Example: GET /api/v1/approvals -> {"items": [...], "version": 3}
    """
    inbox = getattr(request.app.state, "approvals_inbox", None)
    if inbox is None:
        return ApprovalsResponse()
    items = await inbox.list_items()
    if principal.is_peer:
        try:
            install_id = await asyncio.to_thread(_install_id)
        except (OSError, ValueError) as exc:
            logger.info("approvals_install_id_unreadable", error_type=type(exc).__name__)
            install_id = None
        return ApprovalsResponse(items=peer_items.serve(items, install_id), version=inbox.version)
    items = valid_items(items + await peer_items.peer_items(peer_auth.open_db))
    return ApprovalsResponse(items=items, version=inbox.version)

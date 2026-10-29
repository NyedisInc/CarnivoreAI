
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from src.api.error_response import refusal_error
from src.api import peer_auth
from src.api.auth import require_auth
from src.config import settings
from src.core.db import DatastoreUnreadableError
from src.core.federation import pairing, peer_fanout, peer_folders, peer_forward, peer_links
from src.core.federation.project_folder_browse import FolderBrowseRefused, FolderListing, list_project_folders

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["filesystem"])

MAX_CONCURRENT_LISTINGS = 3
_listing_slots = asyncio.Semaphore(MAX_CONCURRENT_LISTINGS)


@router.get("/filesystem/project-folders", response_model=FolderListing,
            dependencies=[Depends(peer_auth.require_peer_sessions)])
async def get_project_folders(request: Request, path: Optional[str] = Query(None, max_length=4096)) -> FolderListing:
    """This computer's folders under its own project roots, directories only, for a paired computer's folder step."""
    principal = "peer" if peer_fanout.is_peer_call(request) else "owner"
    if _listing_slots.locked():
        logger.info("folder_browse_busy", principal=principal)
        raise HTTPException(status_code=503, detail={"code": "busy", "detail": "this computer is listing folders for others, try again"})
    try:
        async with _listing_slots:
            listing = await run_in_threadpool(list_project_folders, path, settings)
    except FolderBrowseRefused as exc:
        raise refusal_error(exc, principal=principal, path_chars=len(path or "")) from None
    logger.info("folder_browse_served", principal=principal, entries=len(listing.entries), truncated=listing.truncated)
    return listing


def _peer_for(host_key: str):
    try:
        with closing(peer_auth.open_db()) as conn:
            return peer_forward.create_peer(conn, host_key)
    except (DatastoreUnreadableError, sqlite3.Error):
        return None


@router.get("/filesystem/computer/{host_key}/browse", dependencies=[Depends(require_auth)])
async def get_computer_folders(host_key: str, request: Request,
                               path: Optional[str] = Query(None, max_length=4096)) -> Dict[str, Any]:
    """One paired computer's folders under its own project roots, asked now; never an error, always a status."""
    if peer_fanout.is_peer_call(request):
        return {"status": "unavailable", "reason": "not_local"}
    peer = await run_in_threadpool(_peer_for, host_key)
    if peer is None:
        shown: Dict[str, Any] = {"status": "unavailable", "reason": "not_paired"}
    else:
        links = peer_links.LINKS
        if links is None or links.client(peer.peer_install_id) is None:
            shown = {"status": "unavailable", "reason": "disconnected"}
        elif links.minor(peer.peer_install_id) < pairing.FOLDER_BROWSE_MINOR:
            shown = {"status": "unavailable", "reason": "peer_too_old"}
        else:
            answers = await peer_fanout.ask_peers(peer_folders.path_for(path), peer_auth.open_db, only=peer.key)
            shown = peer_folders.shown_for(answers)
    logger.info("peer_folder_browse", host_key=host_key, status=shown["status"],
                reason=shown.get("reason") or shown.get("code"), entries=len(shown.get("entries", [])),
                truncated=shown.get("truncated"))
    return shown

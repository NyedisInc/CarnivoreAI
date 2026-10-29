
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.config import settings
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.exports import store
from src.models.exports import ExportBundle, ExportBundleList, ExportedConversation, ExportLocation

logger = structlog.get_logger()
router = APIRouter(tags=["exports"])


def _wire(bundle: store.Bundle) -> ExportBundle:
    return ExportBundle(
        bundle_id=bundle.bundle_id, sha256=bundle.sha256, scope=bundle.scope, project_uid=bundle.project_uid,
        session_uuid=bundle.session_uuid, label=bundle.label, created_at=store.iso_utc(bundle.created_at) or "",
        locations=[ExportLocation(where=loc.where, verified_at=store.iso_utc(loc.verified_at)) for loc in bundle.locations],
        verified_at=store.iso_utc(bundle.verified_at), local_removed=bundle.local_removed, conversations=bundle.conversations)


def _db_path():
    return db_path_for(settings.get_state_dir())


def _read(work):
    try:
        with closing(connect(_db_path(), create=False)) as conn:
            return work(conn)
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.error("exports_read_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="the export status cannot be read")


@router.get("/exports", response_model=ExportBundleList, dependencies=[Depends(require_auth)])
async def list_exports() -> ExportBundleList:
    """Every export bundle, newest first.

    Output: ExportBundleList. Raises: HTTPException 503 - the datastore cannot be read.
    """
    bundles = await run_in_threadpool(_read, store.list_bundles)
    return ExportBundleList(bundles=[_wire(b) for b in bundles], count=len(bundles))


@router.get("/exports/conversations/{conversation_id}", response_model=ExportedConversation,
            dependencies=[Depends(require_auth)])
async def get_exported_conversation(conversation_id: str,
                                    family: Optional[str] = Query(None, description="claude or codex; omit for either")):
    """The export pointer of one conversation and the bundle that holds it.

    Inputs: conversation_id (path); family (query, claude or codex). Output: ExportedConversation.
    Raises: HTTPException 404 ``{"code": "export_not_found"}`` - never exported; 422 - a family that is not claude or
    codex; 503 - the datastore cannot be read.
    """
    if family is not None and family not in store.FAMILIES:
        raise HTTPException(status_code=422, detail=f"family must be one of {list(store.FAMILIES)}")

    def work(conn: sqlite3.Connection):
        found = store.pointer(conn, conversation_id, family)
        return None if found is None else (found, store.bundle(conn, found.bundle_id))

    try:
        answer = await run_in_threadpool(_read, work)
    except store.BundleNotFound:
        answer = None
    if answer is None:
        raise HTTPException(status_code=404, detail={"code": "export_not_found", "message": "that conversation was never exported"})
    found, bundle = answer
    return ExportedConversation(conversation_id=found.conversation_id, family=found.family, title=found.title,
                                exported_at=store.iso_utc(found.exported_at) or "", bundle=_wire(bundle))

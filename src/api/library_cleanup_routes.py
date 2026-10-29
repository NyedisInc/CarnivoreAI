from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Any, Callable, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from src.api import projects_service
from src.api.auth import require_auth
from src.config import settings
from src.core import session_store
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.library_cleanup import projects, sessions
from src.core.library_cleanup.errors import CleanupNotFound, CleanupRefused
from src.core.pipeline import triggers as save_triggers

logger = structlog.get_logger()
router = APIRouter(prefix="/library", tags=["library"], dependencies=[Depends(require_auth)])


class MergeBody(BaseModel):
    """The project that stays, and whether two different folders may merge."""

    into: int = Field(..., description="id of the project that stays")
    allow_different_folder: bool = Field(
        False, description="merge two different canonical folders (a person's call, never mechanical)")


def _db_path():
    path = db_path_for(settings.get_state_dir())
    if not path.exists():
        raise HTTPException(status_code=503, detail={"code": "no_datastore", "detail": str(path)})
    return path


async def _run(write: Callable[[sqlite3.Connection], Dict[str, Any]]) -> Dict[str, Any]:
    path = _db_path()

    def run() -> Dict[str, Any]:
        with closing(connect(path, create=False)) as conn:
            return write(conn)

    try:
        return await run_in_threadpool(run)
    except CleanupNotFound as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "detail": exc.detail})
    except CleanupRefused as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "detail": exc.detail})
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.error("library_cleanup_datastore_error", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail={"code": "datastore_unavailable", "detail": str(exc)})


@router.post("/projects/{source_id}/merge")
async def merge_project(source_id: int, body: MergeBody) -> Dict[str, Any]:
    """Merge project ``source_id`` into ``body.into``.

    Description: re-points every session row and conversation index row, then
      deletes the empty source row with a tombstone, in one transaction. Two
      spellings of one folder merge freely; two different folders only with
      ``allow_different_folder``.
    Inputs: source_id (path int). body (MergeBody).
    Output: dict {source, target, sessions_moved, index_rows_moved, same_folder}.
    Raises: 404 no_project; 409 same_project / different_folder; 503.
    """
    projects_service.guard_writable(settings)
    return await _run(lambda conn: projects.merge_projects(
        conn, source_id, body.into, allow_different_folder=body.allow_different_folder))


@router.delete("/sessions/{session_uuid}")
async def delete_session(session_uuid: str, purge: bool = Query(
        False, description="HARD purge an already soft-deleted row (junk only). "
                           "Default false: the soft delete, which keeps the row")) -> Dict[str, Any]:
    """Delete one session row: soft by default, hard only with ``purge=true``.

    Description: the default is the same soft delete as
      ``DELETE /sessions/records/{uuid}`` (``archived_at`` stamped, row kept),
      because a normal delete stops at the archive. ``purge=true`` removes a row
      that is ALREADY soft-deleted, with its notes, group memberships and
      lineage links; a visible row is refused, so a purge always takes two calls.
    Inputs: session_uuid (path). purge (query bool).
    Output: dict {mode: 'soft'|'purge', ...}.
    Raises: 404 no_session; 409 not_archived / live_session / has_children; 503.
    """
    if not purge:
        def soft(conn: sqlite3.Connection) -> Dict[str, Any]:
            try:
                performed = session_store.archive_session(conn, session_uuid)
            except session_store.SessionNotFoundError:
                raise CleanupNotFound("no_session", f"no session record {session_uuid}")
            return {"mode": "soft", "session_uuid": session_uuid, "performed": performed}
        result = await _run(soft)
        if result["performed"]:
            save_triggers.schedule_for_uuid(session_uuid, save_triggers.EVENT_REMOVE)
        return result
    result = await _run(lambda conn: sessions.purge_session(conn, session_uuid))
    result["mode"] = "purge"
    return result

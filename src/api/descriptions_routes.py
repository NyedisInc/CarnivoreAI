
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.config import settings
from src.core.db import DatastoreUnreadableError, connect, db_path_for
from src.core.descriptions import roster, store
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.models.descriptions import SessionDescriptionRequest, SessionDescriptionResponse

logger = structlog.get_logger()
router = APIRouter()


def _open_or_503():
    try:
        return connect(db_path_for(settings.get_state_dir()), create=False)
    except DatastoreUnreadableError as exc:
        raise HTTPException(status_code=503, detail=f"the datastore cannot be read: {exc}")


@router.patch(
    "/sessions/records/{session_uuid}/description",
    response_model=SessionDescriptionResponse,
    dependencies=[Depends(require_auth)],
)
async def set_session_description(request: Request, session_uuid: str, body: SessionDescriptionRequest):
    """Set one session's short and/or long description. Durably, then the listing push is woken.

    Inputs: request (Request) - for ``app.state.listing_publisher``; session_uuid (str, path) - the row;
      body (SessionDescriptionRequest) - omit a field to keep it, "" clears it.
    Output: SessionDescriptionResponse - the committed values, read back.
    Raises: HTTPException 400 - no field, a line break in the short one or a control character in either;
      404 - no row carries that uuid; 422 - over a cap (120 / 2000); 503 - the datastore is unreadable.
    """
    if body.short_description is None and body.long_description is None:
        raise HTTPException(status_code=400, detail="send short_description and/or long_description")
    try:
        short = store.clean_text(body.short_description, single_line=True)
        long_ = store.clean_text(body.long_description, single_line=False)
    except store.DescriptionInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    def write() -> dict:
        with closing(_open_or_503()) as conn:
            return store.set_session_descriptions(conn, session_uuid, short_description=short, long_description=long_)

    try:
        answer = await run_in_threadpool(write)
    except store.SessionDescriptionNotFound:
        raise HTTPException(status_code=404, detail=f"no session row {session_uuid}")
    except sqlite3.Error as exc:
        logger.error("session_description_write_failed", session_uuid=session_uuid, error=type(exc).__name__)
        raise HTTPException(status_code=503, detail="the description could not be saved")
    publisher = getattr(request.app.state, "listing_publisher", None)
    if publisher is not None:
        publisher.wake()
    return SessionDescriptionResponse(**answer)


@router.get("/sessions/roster", dependencies=[Depends(require_auth)])
async def get_roster(
    request: Request,
    scope: str = Query(roster.SCOPE_ONLINE, description="online (live only), around (live and asleep, never "
                                                         "archived) or all (every row, archived included)"),
    has_description: str = Query(roster.HAS_ANY, description="any, short, long, none (neither) or missing "
                                                              "(lacks at least one)"),
    project: Optional[str] = Query(None, description="A project id or name"),
    company: Optional[str] = Query(None, description="A company id or name; includes every company under it"),
    detail: bool = Query(False, description="Add long descriptions and each session's folder"),
) -> dict:
    """
    Inputs: request (Request) - for ``app.state.session_manager``; the filters above.
    Output: dict ``{scope, filters, total, truncated, sessions, note?}`` (``roster.build_roster``).
    Raises: HTTPException 400 - an unknown scope or has_description; 503 - the datastore is unreadable.
    """
    infos = [i for i in await request.app.state.session_manager.list_session_infos() if i.host_key == LOCAL_HOST_KEY]

    def read() -> roster.RosterContext:
        with closing(_open_or_503()) as conn:
            return roster.read_context(conn)

    try:
        ctx = await run_in_threadpool(read)
    except sqlite3.Error as exc:
        logger.error("roster_read_failed", error=type(exc).__name__)
        raise HTTPException(status_code=503, detail="the roster could not be read")
    try:
        return roster.build_roster(ctx, infos, scope=scope, has_description=has_description, project=project,
                                   company=company, detail=detail)
    except roster.RosterRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc))

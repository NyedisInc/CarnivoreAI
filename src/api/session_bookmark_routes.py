
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from src.api.auth import require_auth
from src.api.error_response import api_error
from src.core.bookmarks import actions, preview, service, store
from src.core.bookmarks.errors import BookmarkError
from src.models.bookmarks import (AddBookmarkRequest, AllBookmarks, Bookmark, BookmarkList, BookmarkPreview, BranchResponse,
                                  CompactionPreview, ConfirmRequest, PointRequest, RewindPointRequest, RewindResponse, TurnPage)

logger = structlog.get_logger()
router = APIRouter(tags=["session-bookmarks"], dependencies=[Depends(require_auth)])


def _http(exc: BookmarkError) -> HTTPException:
    return api_error(exc.status, exc.code, exc)


def _preflight(row) -> None:
    from src.api.launch_profile_errors import refuse_gone_profile
    from src.config import settings

    refuse_gone_profile(settings, row.agent_type, row.launch_record)


@router.get("/bookmarks", response_model=AllBookmarks)
async def list_all_bookmarks(limit: int = Query(store.MAX_RECENT, ge=1, le=store.MAX_RECENT)) -> AllBookmarks:
    """Recent bookmarks across every session, newest first, each with its session's name.

    ``compactions`` carries the newest automatic compaction points of every Claude session in the same answer (one
    batched read, each with its session's ``session_row_id`` and name), so the all-sessions widget needs no per-session
    fetch. PUSHED: the store names ``bookmarks:*`` on every add and delete, and a recorded compaction names it too. Example: GET /api/v1/bookmarks?limit=50
    """
    return AllBookmarks(**await run_in_threadpool(service.list_all, limit))


@router.get("/sessions/{session_uuid}/bookmarks", response_model=BookmarkList)
async def list_bookmarks(session_uuid: str) -> BookmarkList:
    """A session's bookmarks, newest first, plus `compactions`: an automatic bookmark per /compact point (derived, not stored).

    Branch or rewind a compaction with its `entry_uuid` on the point routes. Example: GET /api/v1/sessions/<uuid>/bookmarks.
    """
    try:
        return BookmarkList(**await run_in_threadpool(service.list_bookmarks, session_uuid))
    except BookmarkError as exc:
        raise _http(exc)


@router.post("/sessions/{session_uuid}/bookmarks", response_model=Bookmark, status_code=201)
async def add_bookmark(session_uuid: str, body: AddBookmarkRequest) -> Bookmark:
    """Bookmark the latest turn, the newest record, or a turn from the past-turns list.

    Example: POST /api/v1/sessions/<uuid>/bookmarks {"label": "before the refactor"}
    """
    try:
        made = await run_in_threadpool(lambda: service.add_bookmark(
            session_uuid, label=body.label, entry_uuid=body.entry_uuid, point=body.point, created_by=body.created_by))
    except BookmarkError as exc:
        raise _http(exc)
    return Bookmark(**made.as_dict())


@router.delete("/bookmarks/{bookmark_id}", response_model=Bookmark)
async def delete_bookmark(bookmark_id: int) -> Bookmark:
    """Remove a bookmark. No transcript is touched. Example: DELETE /api/v1/bookmarks/7."""
    try:
        gone = await run_in_threadpool(service.delete_bookmark, bookmark_id)
    except BookmarkError as exc:
        raise _http(exc)
    return Bookmark(**gone.as_dict())


@router.get("/bookmarks/{bookmark_id}/preview", response_model=BookmarkPreview)
async def preview_bookmark(bookmark_id: int,
                           turns: Optional[int] = Query(None, ge=1, le=preview.MAX_PREVIEW_TURNS)) -> BookmarkPreview:
    """The last ``turns`` chat messages up to a bookmark's point, oldest first, read from its transcript.

    ``turns`` defaults to the bookmarks widget's ``previewTurns`` setting (4 until chosen otherwise). 409
    ``transcript_unavailable`` when the conversation is not on this computer. No transcript is modified.
    Example: GET /api/v1/bookmarks/7/preview?turns=4
    """
    try:
        return BookmarkPreview(**await run_in_threadpool(preview.bookmark_preview, bookmark_id, turns))
    except BookmarkError as exc:
        raise _http(exc)


@router.get("/sessions/{session_uuid}/compactions/{entry_uuid}/preview", response_model=CompactionPreview)
async def preview_compaction(session_uuid: str, entry_uuid: str,
                             turns: Optional[int] = Query(None, ge=1, le=preview.MAX_PREVIEW_TURNS)) -> CompactionPreview:
    """The last ``turns`` chat messages BEFORE a compaction point (an automatic bookmark), oldest first.

    ``entry_uuid`` is the ``compactions[].entry_uuid`` of ``GET /sessions/{id}/bookmarks``; 404 ``entry_not_found``
    when it is not a compaction of the session. ``turns`` defaults to the bookmarks widget's ``previewTurns``
    setting, as the bookmark preview. 409 ``transcript_unavailable`` when the conversation is not on this computer.
    Example: GET /api/v1/sessions/<uuid>/compactions/<boundary>/preview?turns=4
    """
    try:
        return CompactionPreview(**await run_in_threadpool(preview.compaction_preview, session_uuid, entry_uuid, turns))
    except BookmarkError as exc:
        raise _http(exc)


@router.get("/sessions/{session_uuid}/turns", response_model=TurnPage)
async def list_turns(session_uuid: str, offset: int = Query(0, ge=0),
                     limit: int = Query(50, ge=1, le=service.MAX_TURNS_PAGE)) -> TurnPage:
    """The human prompts of the session's current conversation, newest first, paged.

    Example: GET /api/v1/sessions/<uuid>/turns?offset=0&limit=50
    """
    try:
        return TurnPage(**await run_in_threadpool(lambda: service.turns_page(session_uuid, offset=offset, limit=limit)))
    except BookmarkError as exc:
        raise _http(exc)


@router.post("/sessions/{session_uuid}/branch", response_model=BranchResponse, status_code=201)
async def branch_point(request: Request, session_uuid: str, body: PointRequest) -> BranchResponse:
    """Branch from here: open a NEW session on a copy cut at the point. The original is never modified."""
    try:
        made = await actions.branch(request.app.state.session_manager, session_uuid=session_uuid,
                                    entry_uuid=body.entry_uuid, conversation=body.conversation, preflight=_preflight)
    except BookmarkError as exc:
        raise _http(exc)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise api_error(500, "session_fork_failed", exc, session_uuid=session_uuid, step="bookmark_branch") from exc
    return BranchResponse(**made)


@router.post("/sessions/{session_uuid}/rewind", response_model=RewindResponse)
async def rewind_point(request: Request, session_uuid: str, body: RewindPointRequest) -> RewindResponse:
    """Rewind in place: restart THIS live session on a copy cut at the point.

    Gates: ``confirm`` true (the ticked arm box; 400 otherwise), the row measured running (409
    ``not_live`` otherwise), no restart of it already in flight (409). The original transcript
    stays on disk, so a later bookmark of it is the way back.
    """
    try:
        done = await actions.rewind(request.app.state.session_manager, session_uuid=session_uuid,
                                    entry_uuid=body.entry_uuid, confirm=body.confirm, conversation=body.conversation)
    except BookmarkError as exc:
        raise _http(exc)
    except ValueError as exc:
        raise api_error(400, "restart_refused", exc)
    return RewindResponse(**done)


async def _bookmark(bookmark_id: int) -> store.Bookmark:
    try:
        return await run_in_threadpool(store.get_store().get, bookmark_id)
    except BookmarkError as exc:
        raise _http(exc)


@router.post("/bookmarks/{bookmark_id}/branch", response_model=BranchResponse, status_code=201)
async def branch_bookmark(request: Request, bookmark_id: int) -> BranchResponse:
    """Branch from a stored bookmark (into the conversation it was taken in). Example: POST /api/v1/bookmarks/7/branch."""
    mark = await _bookmark(bookmark_id)
    return await branch_point(request, mark.session_uuid,
                              PointRequest(entry_uuid=mark.entry_uuid, conversation=mark.claude_session_uuid))


@router.post("/bookmarks/{bookmark_id}/rewind", response_model=RewindResponse)
async def rewind_bookmark(request: Request, bookmark_id: int, body: ConfirmRequest) -> RewindResponse:
    """Rewind the bookmark's own session to it, behind the same gates as ``POST .../rewind``."""
    mark = await _bookmark(bookmark_id)
    return await rewind_point(request, mark.session_uuid, RewindPointRequest(
        entry_uuid=mark.entry_uuid, conversation=mark.claude_session_uuid, confirm=body.confirm))

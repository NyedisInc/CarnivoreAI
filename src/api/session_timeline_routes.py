
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from src.api.error_response import refusal_error
from src.api.auth import require_auth
from src.core.bookmarks.errors import BookmarkError
from src.core.session_timeline import constants as C
from src.core.session_timeline import gather, peek
from src.models.session_timeline import SessionTimeline, TimelinePeek

router = APIRouter(tags=["session-timeline"], dependencies=[Depends(require_auth)])


def _http(exc: BookmarkError) -> HTTPException:
    return refusal_error(exc)


@router.get("/sessions/{session_uuid}/timeline", response_model=SessionTimeline)
async def session_timeline(session_uuid: str) -> SessionTimeline:
    """The session's conversations oldest first (current last) as bars, with their marks and sleep gaps.

    Marks are compacts (with the context dropped where claude recorded it), bookmarks, restarts and restore points;
    a fork, branch or rewind bar carries ``began.split`` (the conversation and message it was cut from, dated when its
    transcript can be read). Each bar carries its busy and idle band (``activity``, ``busy_seconds``) from ONE read of
    the stats plugin's per-minute activity, null where the stats never measured it. 404 ``session_not_found``.
    Example: GET /api/v1/sessions/7/timeline
    """
    try:
        return SessionTimeline(**await run_in_threadpool(gather.build, session_uuid))
    except BookmarkError as exc:
        raise _http(exc)


@router.get("/sessions/{session_uuid}/timeline/peek", response_model=TimelinePeek)
async def session_timeline_peek(session_uuid: str, conversation: str = Query(..., min_length=1),
                                entry_uuid: str = Query(..., min_length=1),
                                turns: Optional[int] = Query(None, ge=1, le=C.MAX_PEEK_TURNS)) -> TimelinePeek:
    """The last ``turns`` chat messages up to a point of one of the session's conversations, oldest first.

    404 ``entry_not_found`` when the point (or a conversation the session does not hold) is unknown, 409
    ``transcript_unavailable`` when the transcript is not on this computer, 409 ``not_claude`` for a Codex session.
    Example: GET /api/v1/sessions/7/timeline/peek?conversation=<uuid>&entry_uuid=<uuid>&turns=4
    """
    try:
        return TimelinePeek(**await run_in_threadpool(peek.peek, session_uuid, conversation, entry_uuid, turns))
    except BookmarkError as exc:
        raise _http(exc)

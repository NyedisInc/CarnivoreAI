
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from src.api.auth import require_auth
from src.config import settings
from src.core import cross_session_search as search

router = APIRouter()


class ScrollbackMatch(BaseModel):
    """One matching row: where it is, and the text around the match."""

    line: int
    occurrence_from_end: int
    before: str
    match: str
    after: str


class ScrollbackSessionHits(BaseModel):
    """One session's matches, newest first."""

    session_id: str
    tmux_session: str
    match_count: int
    matches: List[ScrollbackMatch]
    truncated: bool
    alternate_screen: bool
    error: Optional[str] = None


class ScrollbackSearchResult(BaseModel):
    """The whole answer. ``sessions`` lists only sessions with something to say."""

    query: str
    sessions: List[ScrollbackSessionHits]
    searched: int
    total_matches: int
    truncated: bool
    timed_out: int


def _scrollback_depth() -> int:
    try:
        return int(settings.load_auth_config().session.scrollback_lines)
    except (OSError, ValueError, AttributeError) as exc:
        search.logger.warning("cross_search_depth_unreadable", error=str(exc))
        return search.MAX_LINES_PER_SESSION


@router.get(
    "/sessions/scrollback-search",
    response_model=ScrollbackSearchResult,
    dependencies=[Depends(require_auth)],
)
async def scrollback_search(
    request: Request, q: str = Query("", max_length=search.MAX_QUERY_CHARS * 4)
) -> ScrollbackSearchResult:
    """Search the scrollback of every live session this app runs.

    Inputs: q (query string) - literal text, case-insensitive, 2 to 200
      characters after trimming. Never a pattern.
    Output: ScrollbackSearchResult.
    Raises: HTTPException 422 with ``{"code": "too_short" | "too_long"}``.
    Example: GET /api/v1/sessions/scrollback-search?q=traceback
    """
    try:
        query = search.normalize_query(q)
    except search.QueryRejected as exc:
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    manager = request.app.state.session_manager
    targets = search.collect_targets(manager, manager._tmux_socket_name())
    answer = await search.search_targets(targets, query, lines=_scrollback_depth())
    return ScrollbackSearchResult(**answer)

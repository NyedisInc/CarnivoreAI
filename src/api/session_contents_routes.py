
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.api.error_response import refusal_error
from src.api.auth import require_auth
from src.core.bookmarks.errors import BookmarkError
from src.core.session_contents import gather
from src.models.session_contents import SessionContents

router = APIRouter(tags=["session-contents"], dependencies=[Depends(require_auth)])


@router.get("/sessions/{session_uuid}/contents", response_model=SessionContents)
async def session_contents(session_uuid: str, request: Request) -> SessionContents:
    """The session's files by section, from its pane's config dir and its project.

    404 ``session_not_found``; 409 ``remote_host`` (a paired computer's session) or ``unsupported_family``
    (neither Claude Code nor Codex); 503 ``datastore_unreadable``.
    Example: GET /api/v1/sessions/7/contents
    """
    manager = getattr(request.app.state, "session_manager", None)
    socket = manager.tmux_socket_name() if manager is not None else None
    try:
        return SessionContents(**await gather.read(session_uuid, socket))
    except BookmarkError as exc:
        raise refusal_error(exc, session_uuid=session_uuid) from exc


from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.session_pane_facts import read_pane_facts
from src.models.session_pane_facts import SessionPaneFacts

logger = structlog.get_logger()
router = APIRouter()


@router.get(
    "/sessions/{session_id}/pane-facts",
    response_model=SessionPaneFacts,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_session_pane_facts(request: Request, session_id: str) -> SessionPaneFacts:
    """Live cwd, foreground command, git branch and size of one session's pane.

    Description: resolves the session through ``get_session_info``, which
      accepts a created id and an ``adopted:<tmux-name>`` id, and asks tmux
      about the STORED ``tmux_session`` on the wrapper (gotcha 1 and 4b).
    Inputs: request (Request); session_id (str) - a session row id.
    Output: SessionPaneFacts - every field None when the pane is unreadable.
    Raises: HTTPException 404 - no session carries this id.
    Example: GET /api/v1/sessions/ses_1/pane-facts -> {"cwd_display": "~/src", ...}
    """
    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_id, "the pane facts read")
    info = await session_manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    tmux_name = info.tmux_session
    if not tmux_name:
        return SessionPaneFacts()
    facts = await read_pane_facts(session_manager._tmux_socket_name(), tmux_name)
    logger.debug("session_pane_facts_read", session_id=session_id, readable=facts.cwd is not None)
    return facts

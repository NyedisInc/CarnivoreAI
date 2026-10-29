
from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.background_work import interrupt as bw_interrupt
from src.core.background_work import tree as bw_tree
from src.core.sessions.errors import SessionInputFailed, SessionNotFound
from src.models.background_work import InterruptRequest, InterruptResponse
from src.api.error_response import api_error

logger = structlog.get_logger()
router = APIRouter()

REFUSE_GONE: str = "session_gone"
REFUSE_NOT_RUNNING: str = "session_not_running"


def _refuse(session_id: str, code: str, message: str) -> HTTPException:
    logger.info("session_interrupt_refused", session_id=session_id, code=code, reason=message)
    return HTTPException(status_code=409, detail={"code": code, "message": message})


async def send_escape(session_manager: Any, session_id: str) -> InterruptResponse:
    info = await session_manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    activity_status = info.activity_status
    facts = bw_interrupt.check_facts(agent_family=info.agent_family,
                                     activity_status=activity_status)
    if not facts.allowed:
        raise _refuse(session_id, facts.code, facts.detail)
    tmux_name = info.tmux_session
    if not tmux_name:
        raise _refuse(session_id, REFUSE_GONE, "the session carries no tmux session")
    socket = session_manager.tmux_socket_name()
    try:
        tree = await asyncio.to_thread(bw_tree.measure, str(tmux_name), socket)
    except bw_tree.PaneNotFound as exc:
        raise _refuse(session_id, REFUSE_GONE, str(exc)) from exc
    except bw_tree.TreeUnmeasured as exc:
        logger.warning("session_interrupt_unmeasured", session_id=session_id,
                       tmux=tmux_name, error=str(exc))
        raise api_error(503, "service_unavailable", exc, step="send_escape") from exc
    pane = bw_interrupt.check_pane(tree)
    if not pane.allowed:
        raise _refuse(session_id, pane.code, pane.detail)
    try:
        await session_manager.send_input(bw_interrupt.ESCAPE, session_id=session_id)
    except SessionInputFailed as exc:
        raise api_error(502, "session_input_failed", exc) from exc
    except SessionNotFound as exc:
        raise api_error(404, "session_not_found", exc) from exc
    except ValueError as exc:
        raise _refuse(session_id, REFUSE_NOT_RUNNING, str(exc)) from exc
    logger.info(
        "session_interrupt_sent", session_id=session_id, tmux=tmux_name,
        agent_pid=tree.agent_pid, activity_status=activity_status,
        subagents_running=info.subagents_running, background_open=info.background_open,
    )
    return InterruptResponse(sent=True, agent_pid=tree.agent_pid,
                             activity_status=activity_status, detail=pane.detail)


@router.post(
    "/sessions/{session_id}/interrupt",
    response_model=InterruptResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def interrupt_session(
    request: Request, session_id: str, body: InterruptRequest,
) -> InterruptResponse:
    """Send one Escape to a live agent session's pane.

    Description: see the module docstring for every refusal. The row's
      facts are read first, the pane is measured on a worker thread, and
      only then is the key written.
    Inputs: request (Request). session_id (str) - either id shape. body
      (InterruptRequest) - ``{"confirm": true}``.
    Output: InterruptResponse.
    Raises: HTTPException 404 - unknown session; 409 ``{code, message}`` -
      a refusal (``remote_host`` carries ``{code, detail}``); 422 - no
      confirmation; 503 - the pane could not be measured.
    Example: POST /api/v1/sessions/ses_abc/interrupt {"confirm": true}
    """
    del body
    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_id, "interrupting the session")
    return await send_escape(session_manager, session_id)

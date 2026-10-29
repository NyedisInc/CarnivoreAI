"""Interrupt a session's agent with one Escape: ``POST /api/v1/sessions/{id}/interrupt``.

THE KEY TRAVELS THE TERMINAL'S OWN INPUT PATH. ``SessionManager.send_input``
is what the terminal WebSocket calls for every keystroke, so the pane gets
exactly the byte a person pressing Escape in the browser sends, through the
same backend ``write`` (``send-keys -H 1b`` on tmux). This route never
builds a tmux command of its own.

GUARDED, EVERY CLAUSE REQUIRED (``src.core.background_work.interrupt``):
the body confirms (``{"confirm": true}``); the session is local
(``refuse_remote``, 409 ``remote_host``); it is not a plain shell and not
dead (409 ``not_an_agent`` / ``session_dead``, off the WRAPPER, gotcha 1);
its pane, measured fresh by exact name on the manager's socket, exists (409
``session_gone``) and runs a claude or codex process (409
``no_agent_process``); and the backend is running (409
``session_not_running``). Nothing is written until all of them hold. A pane
that could not be measured is 503, never a guess.

THE PATH ID IS NOT THE TMUX NAME (gotcha 4b): the STORED ``tmux_session``
is what is measured, and the id is handed to ``send_input`` exactly as the
WebSocket hands its own.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.background_work import interrupt as bw_interrupt
from src.core.background_work import tree as bw_tree
from src.models.background_work import InterruptRequest, InterruptResponse

logger = structlog.get_logger()
router = APIRouter()

REFUSE_GONE: str = "session_gone"
REFUSE_NOT_RUNNING: str = "session_not_running"


def _refuse(session_id: str, code: str, message: str) -> HTTPException:
    logger.info("session_interrupt_refused", session_id=session_id, code=code, reason=message)
    return HTTPException(status_code=409, detail={"code": code, "message": message})


async def send_escape(session_manager: Any, session_id: str) -> InterruptResponse:
    """Guard, then send one Escape to a LOCAL live agent session's pane (the route's whole body, also a Pack move's interrupt hook).

    Inputs: session_manager; session_id (str) - either id shape. Output: InterruptResponse.
    Raises: HTTPException 404 unknown session, 409 ``{code, message}`` a refusal, 503 the pane could not be measured.
    Example: await send_escape(request.app.state.session_manager, "ses_abc")
    """
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
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    pane = bw_interrupt.check_pane(tree)
    if not pane.allowed:
        raise _refuse(session_id, pane.code, pane.detail)
    try:
        await session_manager.send_input(bw_interrupt.ESCAPE, session_id=session_id)
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

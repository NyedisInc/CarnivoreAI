
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api import projects_service
from src.api.auth import require_auth
from src.config import settings
from src.core import session_change_notice
from src.core.session_move.apply import (
    SessionMoveFailed,
    SessionMoveRefused,
    SessionNotFound,
    apply_move,
    plan_move,
)
from src.models.session_move import SessionMoveRequest, SessionMoveResponse

logger = structlog.get_logger()
router = APIRouter(tags=["sessions"])

NOTICE_REASON = "session_moved"


def _open_conn() -> Any:
    return projects_service.open_db_or_503(settings)


def _tell_browsers(request: Request, project_created: bool) -> None:
    app = getattr(request, "app", None)
    if app is not None:
        session_change_notice.publish(app.state, session_change_notice.build_structural_notice(NOTICE_REASON))
    if project_created:
        from src.core.resource_push import notify, topics

        notify(topics.PROJECTS)


@router.post("/sessions/{session_uuid}/move-folder", response_model=SessionMoveResponse,
             dependencies=[Depends(require_auth)])
async def move_session_folder(session_uuid: str, body: SessionMoveRequest, request: Request) -> SessionMoveResponse:
    """Plan or run a move of one session into an existing project or a new folder.

    Description: carries the temp folder's files (``.cc.theme`` stays), backs them up first under the
      state directory and verifies the count, restarts the pane IN THE SAME TMUX SESSION in the new
      folder as a resume of the same conversation (``respawn-pane -c``), measures that the pane is
      there, then writes ``working_dir`` and the project pair in one update. The conversation's
      transcript is not moved or copied: claude finds it by its id from any folder.
    Inputs: session_uuid (str, URL) - the row's ``session_uuid``; body (SessionMoveRequest); request.
    Output: SessionMoveResponse - the plan; ``applied`` and ``done`` after a run.
    Raises: HTTPException 404 unknown session; 409 a refused apply (detail: ``code``, ``message``, ``plan``)
      or another move running; 500 a step failed (detail names the step, any file not put back and the
      backup folder); 503 database unreachable or read-only.
    """
    manager = request.app.state.session_manager
    try:
        if not body.apply:
            plan = await plan_move(manager, _open_conn, session_uuid, project_id=body.project_id,
                                   new_folder=body.new_folder, settings=settings)
            return SessionMoveResponse(**plan.to_wire())
        projects_service.guard_writable(settings)
        answer = await apply_move(manager, _open_conn, session_uuid, project_id=body.project_id,
                                  new_folder=body.new_folder, settings=settings,
                                  confirm_restart_live=body.confirm_restart_live)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail={"code": "session_not_found",
                                                     "message": "no running session on this computer has that id"})
    except SessionMoveRefused as exc:
        raise HTTPException(status_code=409, detail={
            "code": exc.code, "message": str(exc), "plan": exc.plan.to_wire() if exc.plan else None})
    except SessionMoveFailed as exc:
        logger.error("session_move_failed", session_uuid=session_uuid, step=exc.step, error=str(exc),
                     undo_errors=exc.undo_errors, backup=exc.backup)
        raise HTTPException(status_code=500, detail={
            "code": "move_failed", "step": exc.step, "message": str(exc), "undo_errors": exc.undo_errors,
            "backup": exc.backup})
    _tell_browsers(request, bool((answer.get("done") or {}).get("project_created")))
    return SessionMoveResponse(**answer)


from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.api.remote_route_guard import remote_target
from src.core.session_tasks.reader import TaskReader
from src.core.session_tasks.service import all_tasks, tasks_for
from src.core.session_tasks.watch import ALL_KEY, SessionTasksWatch
from src.models.session_tasks import AllSessionTasks, SessionTasks

router = APIRouter(tags=["session-tasks"])


def watch_and_reader(app_state: Any) -> tuple[SessionTasksWatch, TaskReader]:
    if getattr(app_state, "session_tasks_watch", None) is None:
        app_state.session_tasks_watch = SessionTasksWatch()
        app_state.session_tasks_reader = TaskReader()
    return app_state.session_tasks_watch, app_state.session_tasks_reader


@router.get("/sessions/{session_id}/tasks", response_model=SessionTasks, dependencies=[Depends(require_auth)])
async def get_session_tasks(request: Request, session_id: str) -> SessionTasks:
    """One session's task list, and a lease that keeps the push going while this client looks.

    Inputs: request (Request); session_id (str) - a session row id (created or ``adopted:``).
    Output: SessionTasks - ``empty`` when the agent wrote no list, ``unknown`` when the transcript could not be read,
      ``unsupported`` for a non-claude session, ``remote`` for a paired-computer session.
    Raises: HTTPException 404 - no session carries this id.
    Example: GET /api/v1/sessions/ses_1/tasks -> {"state": "ok", "tasks": [{"id": "1", "status": "in_progress", ...}]}
    """
    manager = request.app.state.session_manager
    if remote_target(manager, session_id) is not None:
        return SessionTasks(state="remote", session_id=session_id)
    if await manager.get_session_info(session_id) is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    watch, reader = watch_and_reader(request.app.state)

    async def load() -> SessionTasks:
        info = await manager.get_session_info(session_id)
        return await tasks_for(info, reader) if info is not None else SessionTasks(state="unknown", session_id=session_id)

    return await watch.read(session_id, load)


@router.get("/session-tasks", response_model=AllSessionTasks, dependencies=[Depends(require_auth)])
async def get_all_session_tasks(request: Request) -> AllSessionTasks:
    """Every live session that has a task list, grouped one entry per session, and a lease for the push.

    Inputs: request (Request). Output: AllSessionTasks - sessions with no list are left out.
    Example: GET /api/v1/session-tasks -> {"sessions": [{"session_id": "ses_1", "label": "api", "tasks": [...]}]}
    """
    manager = request.app.state.session_manager
    watch, reader = watch_and_reader(request.app.state)
    return await watch.read(ALL_KEY, lambda: all_tasks(manager, reader))

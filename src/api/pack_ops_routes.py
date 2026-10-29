
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.api import projects_service
from src.api.auth import require_auth
from src.config import settings
from src.core.pack.move import inflight, op_status

logger = structlog.get_logger()
router = APIRouter()


def _read(fn: Any) -> Any:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        return fn(conn)


@router.get("/pack/ops", dependencies=[Depends(require_auth)])
async def list_ops() -> Dict[str, Any]:
    """Every pack transfer in flight or finished in the last 15 minutes, newest first, in the status shape of ``core/pack/move/op_status.py``.

    Output: {ops: [{id, kind, direction, name, machine, mode, state, step, steps, error_code, error, started_at, finished_at, running,
      interrupted, cancellable, cancel_blocked, session_uuid, target_session_uuid}]}.
    Example: GET /api/v1/pack/ops
    """
    return {"ops": await run_in_threadpool(_read, op_status.recent)}


@router.post("/pack/ops/{op_id}/cancel", dependencies=[Depends(require_auth)])
async def cancel_op(op_id: str) -> Dict[str, Any]:
    """Cancel one transfer that has not reached its point of no return; the session or project stays exactly as it was here.

    Description: a session send is past the point when the other computer is asked to start the agent; a project migrate when it is asked to take
      over. Before that the task is stopped, what was sent is undone, a session put to sleep for the move is woken again, and the op ends
      ``failed`` with ``error_code`` ``cancelled``. An op whose app restarted under it (``interrupted``) is closed the same way.
    Output: {op_id, state: "cancelling" | "closed"}. Raises: 404 ``unknown_op``; 409 ``past_point_of_no_return`` (with the reason),
      ``already_finished``, ``not_cancellable_here`` (the other computer runs it).
    Example: POST /api/v1/pack/ops/3f2a.../cancel
    """
    status = await run_in_threadpool(_read, lambda conn: op_status.one(conn, op_id))
    if status is None:
        raise HTTPException(404, {"code": "unknown_op", "detail": "no such transfer"})
    if not status["running"]:
        raise HTTPException(409, {"code": "already_finished", "detail": "this transfer already finished"})
    if status["direction"] == "in":
        raise HTTPException(409, {"code": "not_cancellable_here", "detail": "the other computer is running this transfer; cancel it there"})
    if status["interrupted"]:
        await run_in_threadpool(_read, lambda conn: op_status.mark_interrupted(conn, op_id))
        return {"op_id": op_id, "state": "closed"}
    outcome = inflight.cancel(op_id)
    if outcome == "locked":
        raise HTTPException(409, {"code": "past_point_of_no_return", "detail": inflight.blocked_reason(op_id) or "this transfer can no longer be stopped"})
    if outcome == "not_running":
        raise HTTPException(409, {"code": "already_finished", "detail": "this transfer already finished"})
    return {"op_id": op_id, "state": "cancelling"}

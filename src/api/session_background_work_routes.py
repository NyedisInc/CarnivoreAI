
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.agent_families import DEFAULT_FAMILY
from src.core.background_work import batch as bw_batch
from src.core.background_work import guard as bw_guard
from src.core.background_work import tree as bw_tree
from src.core.background_work.attribution import LaunchOwners, read_owners
from src.core.background_work.listing import list_processes
from src.core.background_work.terminate import LivenessUnmeasured, terminate
from src.models.background_work import (
    BackgroundProcess,
    SessionBackgroundWork,
    TargetResult,
    TerminateAllRequest,
    TerminateAllResponse,
    TerminateRequest,
    TerminateResponse,
)
from src.api.error_response import api_error, soft_failure

logger = structlog.get_logger()
router = APIRouter()


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


async def _resolve(request: Request, session_id: str, action: str) -> tuple[Any, Any, str]:
    session_manager = request.app.state.session_manager
    refuse_remote(session_manager, session_id, action)
    info = await session_manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
    tmux_name = info.tmux_session
    if not tmux_name:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} has no tmux session")
    return session_manager, info, str(tmux_name)


@router.get(
    "/sessions/{session_id}/background-work",
    response_model=SessionBackgroundWork,
    dependencies=[Depends(require_peer_sessions)],
)
async def get_session_background_work(request: Request, session_id: str) -> SessionBackgroundWork:
    """List the tool shells the session's agent is running, oldest first.

    Description: measures the pane (exact name, the manager's socket) and
      one process table on a worker thread. Only a claude session lists
      anything; codex and shell sessions are ``not_applicable``.
    Inputs: request (Request). session_id (str).
    Output: SessionBackgroundWork.
    Raises: HTTPException 404 - unknown session.
    Example: GET /api/v1/sessions/ses_abc/background-work
    """
    session_manager, info, tmux_name = await _resolve(request, session_id, "the background work read")
    family = info.agent_family
    now = _iso(datetime.now(timezone.utc))
    if family is not None and family != DEFAULT_FAMILY:
        return SessionBackgroundWork(state="not_applicable", family=family, as_of=now,
                                     detail="only claude sessions list their tool shells")
    socket = session_manager.tmux_socket_name()
    try:
        tree = await asyncio.to_thread(bw_tree.measure, tmux_name, socket)
    except bw_tree.TreeError as exc:
        detail = soft_failure("background_work_unmeasured", exc, status=503, session_id=session_id, tmux=tmux_name)
        return SessionBackgroundWork(state="unchecked", family=family, as_of=now, detail=detail)
    if tree.agent_pid is None:
        return SessionBackgroundWork(state="absent", family=family, as_of=now,
                                     detail="no claude process runs in this pane")
    listed = await asyncio.to_thread(list_processes, tree)
    owners = await _owners(session_manager, info, tmux_name) if listed else LaunchOwners("ok")
    return SessionBackgroundWork(
        state="ok", family=family, as_of=now, owners=owners.state,
        detail="tool shells under the agent process; a monitor or sub-agent with "
               "no process of its own is not listed here",
        processes=[
            BackgroundProcess(pid=p.pid, start=p.start, task_id=p.task_id,
                              started_at=_iso(p.started_at), children=p.children,
                              summary=p.summary, agent_id=owners.owner_of(p.task_id))
            for p in listed
        ],
    )


async def _owners(session_manager: Any, info: Any, tmux_name: str) -> LaunchOwners:
    conversation_uuid = session_manager.claude_uuid_for_tmux_name(tmux_name)
    working_dir = info.session.working_dir if info.session is not None else None
    return await asyncio.to_thread(read_owners, conversation_uuid, working_dir=working_dir)


def _guarded_terminate(tmux_name: str, socket: str, pid: int, start: str) -> tuple[bw_guard.Verdict, Any]:
    tree = bw_tree.measure(tmux_name, socket)
    verdict = bw_guard.check(tree, pid, start, self_pids=bw_guard.server_lineage())
    if not verdict.allowed:
        return verdict, None
    return verdict, terminate(verdict.subtree)


@router.post(
    "/sessions/{session_id}/background-work/{pid}/terminate",
    response_model=TerminateResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def terminate_background_process(
    request: Request, session_id: str, pid: int, body: TerminateRequest,
) -> TerminateResponse:
    """Stop one of the session's background processes and its subtree.

    Description: SIGTERM, then SIGKILL after a bounded wait for whatever is
      still the same process. See the module docstring for the guard.
    Inputs: request (Request). session_id (str). pid (int). body
      (TerminateRequest) - ``start``, as the listing returned it.
    Output: TerminateResponse.
    Raises: HTTPException 403 ``{code, message}`` - the guard refused;
      404 - unknown session or pane; 409 - remote; 503 - not measurable.
    Example: POST /api/v1/sessions/ses_abc/background-work/89199/terminate
      {"start": "Mon Sep 28 08:58:46 2026"}
    """
    session_manager, _info, tmux_name = await _resolve(request, session_id, "stopping a process")
    socket = session_manager.tmux_socket_name()
    try:
        verdict, result = await asyncio.to_thread(_guarded_terminate, tmux_name, socket, pid, body.start)
    except bw_tree.PaneNotFound as exc:
        raise api_error(404, "not_found", exc, step="terminate_background_process") from exc
    except (bw_tree.TreeUnmeasured, LivenessUnmeasured) as exc:
        logger.warning("background_work_terminate_unmeasured", session_id=session_id,
                       tmux=tmux_name, pid=pid, error=str(exc))
        raise api_error(503, "service_unavailable", exc, step="terminate_background_process") from exc
    if result is None and verdict.code == bw_guard.REFUSE_GONE:
        return TerminateResponse(pid=pid, outcome="already_gone", detail=verdict.detail)
    if result is None:
        logger.warning("background_work_terminate_refused", session_id=session_id,
                       tmux=tmux_name, pid=pid, code=verdict.code, detail=verdict.detail)
        raise HTTPException(status_code=403, detail={"code": verdict.code, "message": verdict.detail})
    logger.info(
        "background_work_terminated", session_id=session_id, tmux=tmux_name, pid=pid,
        outcome=result.outcome, term=result.term, kill=result.kill,
        survivors=result.survivors, errors=result.errors,
    )
    detail = "; ".join(result.errors.values()) or verdict.detail
    return TerminateResponse(pid=pid, outcome=result.outcome, term=result.term, kill=result.kill,
                             survivors=result.survivors, detail=detail)


def guarded_terminate_all(tmux_name: str, socket: str,
                           targets: list[tuple[int, str]]) -> tuple[list, Any]:
    tree = bw_tree.measure(tmux_name, socket)
    verdicts, members = bw_batch.plan(tree, targets, self_pids=bw_guard.server_lineage())
    return verdicts, (terminate(members) if members else None)


@router.post(
    "/sessions/{session_id}/background-work/terminate-all",
    response_model=TerminateAllResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def terminate_background_processes(
    request: Request, session_id: str, body: TerminateAllRequest,
) -> TerminateAllResponse:
    """Stop the listed background processes, each through the single-stop guard.

    Description: the control center's "stop all" and a sub-agent's "stop"
      (issue #1053). The body is the (pid, start) pairs the listing handed
      out; nothing else is stopped. One fresh measurement, the guard per
      target, one SIGTERM-then-SIGKILL pass over every allowed subtree. A
      refused target is reported per target with its code, never as a
      failure of the whole request.
    Inputs: request (Request). session_id (str). body (TerminateAllRequest).
    Output: TerminateAllResponse.
    Raises: HTTPException 404 - unknown session or pane; 409 - remote;
      422 - an empty or oversized list; 503 - not measurable.
    Example: POST /api/v1/sessions/ses_abc/background-work/terminate-all
      {"targets": [{"pid": 89199, "start": "Mon Sep 28 08:58:46 2026"}]}
    """
    session_manager, _info, tmux_name = await _resolve(request, session_id,
                                                       "stopping background processes")
    socket = session_manager.tmux_socket_name()
    targets = [(t.pid, t.start) for t in body.targets]
    try:
        verdicts, result = await asyncio.to_thread(guarded_terminate_all, tmux_name,
                                                   socket, targets)
    except bw_tree.PaneNotFound as exc:
        raise api_error(404, "not_found", exc, step="terminate_background_processes") from exc
    except (bw_tree.TreeUnmeasured, LivenessUnmeasured) as exc:
        logger.warning("background_work_terminate_all_unmeasured", session_id=session_id,
                       tmux=tmux_name, targets=len(targets), error=str(exc))
        raise api_error(503, "service_unavailable", exc, step="terminate_background_processes") from exc
    answers = bw_batch.outcomes(verdicts, result)
    logger.info(
        "background_work_terminated_many", session_id=session_id, tmux=tmux_name,
        targets=[pid for pid, _ in targets],
        refused={a.pid: a.code for a in answers if a.code},
        term=result.term if result else [], kill=result.kill if result else [],
        survivors=result.survivors if result else [],
    )
    return TerminateAllResponse(
        results=[TargetResult(pid=a.pid, outcome=a.outcome, code=a.code, detail=a.detail)
                 for a in answers],
        term=result.term if result else [], kill=result.kill if result else [],
        survivors=result.survivors if result else [],
    )

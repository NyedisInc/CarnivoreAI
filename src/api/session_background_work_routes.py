
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.peer_auth import require_peer_sessions
from src.api.remote_route_guard import refuse_remote
from src.core.agent_families import DEFAULT_FAMILY
from src.core.agy.identity import info_is_agy, row_is_agy
from src.core.background_work import batch as bw_batch
from src.core.background_work import guard as bw_guard
from src.core.background_work import tree as bw_tree
from src.core.background_work.attribution import LaunchOwners, read_owners
from src.core.background_work import leftovers as bw_leftovers
from src.core.background_work.listing import ListedProcess, list_processes
from src.core.background_work.terminate import LivenessUnmeasured, terminate
from src.models.background_work import (
    BackgroundProcess,
    SessionBackgroundWork,
    StopLeftoversRequest,
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
    fast = getattr(session_manager, "resolve_session_ref", None)
    if callable(fast):
        ref = await fast(session_id)
        if ref is None:
            raise HTTPException(status_code=404, detail=f"No session with id {session_id!r}")
        tmux_name = ref.get("tmux_session")
        if not tmux_name:
            raise HTTPException(status_code=404, detail=f"Session {session_id!r} has no tmux session")
        return session_manager, ref, str(tmux_name)
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
    from src.core.conversation_writers import read_process_table

    session_manager, info, tmux_name = await _resolve(request, session_id, "the background work read")
    family = info.get("agent_family") if isinstance(info, dict) else info.agent_family
    is_agy = row_is_agy(info) if isinstance(info, dict) else info_is_agy(info)
    now = _iso(datetime.now(timezone.utc))
    if family is not None and family not in (DEFAULT_FAMILY, "custom") and not is_agy:
        return SessionBackgroundWork(state="not_applicable", family=family, as_of=now,
                                     detail="only claude and agy sessions list their tool shells")
    socket = session_manager.tmux_socket_name()
    try:
        tree = await asyncio.to_thread(
            bw_tree.measure, tmux_name, socket,
            table_reader=lambda: read_process_table(max_age=1.0),
        )
    except bw_tree.TreeError as exc:
        detail = soft_failure("background_work_unmeasured", exc, status=503, session_id=session_id, tmux=tmux_name)
        return SessionBackgroundWork(state="unchecked", family=family, as_of=now, detail=detail)
    agent_row = tree.table.rows.get(tree.agent_pid) if tree.agent_pid is not None else None
    running_agy = bool(agent_row is not None and bw_tree.is_agy_command(agent_row.command))
    if family == "custom" and not is_agy and not running_agy:
        return SessionBackgroundWork(state="not_applicable", family=family, as_of=now,
                                     detail="only claude and agy sessions list their tool shells")
    is_agy = is_agy or running_agy
    if tree.agent_pid is None:
        return SessionBackgroundWork(state="absent", family=family, as_of=now,
                                     detail="no agy process runs in this pane" if is_agy else "no claude process runs in this pane")
    listed = await asyncio.to_thread(list_processes, tree)
    if is_agy:
        owners = LaunchOwners("absent")
        marks = {}
    else:
        owners = await _owners(session_manager, info, tmux_name) if listed else LaunchOwners("ok")
        marks = await _owner_marks(session_manager, info, tmux_name, listed, owners)
    return SessionBackgroundWork(
        state="ok", family=family, as_of=now, owners=owners.state,
        leftovers=bw_leftovers.leftover_count(marks),
        detail="tool shells under the agent process; a monitor or sub-agent with "
               "no process of its own is not listed here",
        processes=[
            BackgroundProcess(pid=p.pid, start=p.start, task_id=p.task_id,
                              started_at=_iso(p.started_at), children=p.children,
                              summary=p.summary, agent_id=owners.owner_of(p.task_id),
                              owner_finished=marks.get(p.pid))
            for p in listed
        ],
    )


def _conversation_ref(session_manager: Any, info: Any, tmux_name: str) -> tuple[Optional[str], Optional[str]]:
    if isinstance(info, dict):
        return (
            info.get("claude_session_uuid") or session_manager.claude_uuid_for_tmux_name(tmux_name),
            info.get("working_dir"),
        )
    working_dir = info.session.working_dir if info.session is not None else None
    return session_manager.claude_uuid_for_tmux_name(tmux_name), working_dir


async def _owner_marks(session_manager: Any, info: Any, tmux_name: str,
                       listed: list[ListedProcess], owners: LaunchOwners) -> dict[int, Optional[bool]]:
    agents = [owners.owner_of(p.task_id) for p in listed]
    wanted = [a for a in agents if a]
    finished = None
    if owners.state == "ok" and wanted:
        uuid, working_dir = _conversation_ref(session_manager, info, tmux_name)
        path = await asyncio.to_thread(bw_leftovers.locate_conversation, uuid, working_dir)
        finished = await asyncio.to_thread(bw_leftovers.finished_agent_ids, path, wanted)
    return dict(bw_leftovers.owner_finished_by_pid(
        listed, owners.by_task, owners.state == "ok", finished if wanted else frozenset()))


async def _owners(session_manager: Any, info: Any, tmux_name: str) -> LaunchOwners:
    conversation_uuid, working_dir = _conversation_ref(session_manager, info, tmux_name)
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


def guarded_stop_leftovers(tmux_name: str, socket: str, listed: list[ListedProcess],
                           marks: dict[int, Optional[bool]],
                           requested: Optional[list[tuple[int, str]]]) -> tuple[bw_leftovers.StopPlan, list, Any]:
    plan = bw_leftovers.plan_stop(listed, marks, requested)
    verdicts, result = guarded_terminate_all(tmux_name, socket, plan.targets) if plan.targets else ([], None)
    return plan, verdicts, result


@router.post(
    "/sessions/{session_id}/background-work/stop-leftovers",
    response_model=TerminateAllResponse,
    dependencies=[Depends(require_peer_sessions)],
)
async def stop_leftover_shells(
    request: Request, session_id: str, body: Optional[StopLeftoversRequest] = None,
) -> TerminateAllResponse:
    """Stop the tool shells a finished sub-agent left behind (issue #2874).

    Description: measures the session's shells and which of them belong to
      a sub-agent that is done, then stops exactly those pids, each
      through the single-stop guard. Never a pattern; nothing runs this on
      its own, the owner chooses. A requested pid that is not a measured
      leftover is reported ``refused`` with code ``not_leftover``.
    Inputs: request (Request). session_id (str). body (StopLeftoversRequest
      | None) - the (pid, start) pairs shown to the user, or none for all.
    Output: TerminateAllResponse.
    Raises: HTTPException 404 - unknown session or pane; 409 - remote;
      422 - an oversized list; 503 - not measurable.
    Example: POST /api/v1/sessions/ses_abc/background-work/stop-leftovers
      {"targets": [{"pid": 89199, "start": "Mon Sep 28 08:58:46 2026"}]}
    """
    session_manager, info, tmux_name = await _resolve(request, session_id, "stopping leftover shells")
    family = info.agent_family
    if family is not None and family != DEFAULT_FAMILY:
        return TerminateAllResponse(results=[])
    socket = session_manager.tmux_socket_name()
    requested = [(t.pid, t.start) for t in body.targets] if body and body.targets else None
    try:
        tree = await asyncio.to_thread(bw_tree.measure, tmux_name, socket)
        listed = await asyncio.to_thread(list_processes, tree) if tree.agent_pid is not None else []
        owners = await _owners(session_manager, info, tmux_name) if listed else LaunchOwners("ok")
        marks = await _owner_marks(session_manager, info, tmux_name, listed, owners)
        plan, verdicts, result = await asyncio.to_thread(
            guarded_stop_leftovers, tmux_name, socket, listed, marks, requested)
    except bw_tree.PaneNotFound as exc:
        raise api_error(404, "not_found", exc, step="stop_leftover_shells") from exc
    except (bw_tree.TreeUnmeasured, LivenessUnmeasured) as exc:
        logger.warning("background_work_stop_leftovers_unmeasured", session_id=session_id,
                       tmux=tmux_name, error=str(exc))
        raise api_error(503, "service_unavailable", exc, step="stop_leftover_shells") from exc
    answers = plan.refused + bw_batch.outcomes(verdicts, result)
    logger.info(
        "background_work_stopped_leftovers", session_id=session_id, tmux=tmux_name,
        targets=[pid for pid, _ in plan.targets],
        refused={a.pid: a.code for a in answers if a.code},
        term=result.term if result else [], kill=result.kill if result else [],
    )
    return TerminateAllResponse(
        results=[TargetResult(pid=a.pid, outcome=a.outcome, code=a.code, detail=a.detail)
                 for a in answers],
        term=result.term if result else [], kill=result.kill if result else [],
        survivors=result.survivors if result else [],
    )

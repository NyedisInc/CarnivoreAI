
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Awaitable, Callable, Dict, Optional, Set

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api import pack_migrate_env as env_mod, pack_move_env, peer_auth, project_transport_routes, projects_service
from src.api.peer_auth import require_peer_sessions
from src.api.project_replica_routes import add_project_replica, find_peer
from src.config import settings
from src.core.federation import peer_links, peer_listing
from src.core.pack.move import inflight
from src.core.pack.carry import step as carry_step
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.migrate import apply
from src.core.pack.migrate.plan import MigrateError
from src.core.pack.move import interrupt, session_move
from src.models.projects import AddReplicaRequest

logger = structlog.get_logger()
router = APIRouter()
pack_capabilities.register("pack.session_move")

MOVE_TIMEOUT_SECONDS = 900.0
_tasks: Set["asyncio.Task[Any]"] = set()


class MoveBody(BaseModel):
    """Which machine, and how long to wait for the turn to end."""

    model_config = ConfigDict(extra="forbid")

    machine: str = Field(min_length=1, max_length=200)
    wait_seconds: int = Field(default=session_move.DEFAULT_WAIT_SECONDS, ge=0, le=3600)


def _http(exc: MigrateError) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "detail": exc.detail, "step": exc.step, "rule": exc.rule})


async def _refresh_listing(peer: Any) -> None:
    try:
        await peer_listing.refresh(peer, peer_links.LINKS, peer_auth.open_db, force=True)
    except (OSError, asyncio.TimeoutError) as exc:
        logger.info("pack_session_move_listing_refresh_failed", error=type(exc).__name__)


async def _project_adder(peer: Any, project_name: str) -> Callable[[], Awaitable[None]]:
    async def add() -> None:
        try:
            view = await add_project_replica(project_name, AddReplicaRequest(machine=peer.peer_install_id))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            raise MigrateError(str(detail.get("code") or "project_add_refused"), str(detail.get("detail") or "the project could not be added there"),
                               exc.status_code, "project") from exc
        if not carry_step.carried_ok(view.get("code")):
            raise carry_step.failure(str(peer.label), view["code"], "project")
    return add


async def start_send(session_uuid: str, machine: str, wait_seconds: int, request: Request, *, mode: str = "move", with_project: bool = False,
                     stop_running: bool = False) -> Dict[str, Any]:
    projects_service.guard_writable(settings)
    peer = await run_in_threadpool(find_peer, machine)
    request_fn = env_mod.link_request(peer.peer_install_id, MOVE_TIMEOUT_SECONDS)
    if request_fn is None:
        raise HTTPException(502, {"code": "machine_unreachable", "detail": f"{peer.label} is not connected right now"})
    env = env_mod.source_env()

    def read() -> Dict[str, Any]:
        with closing(env.open_db()) as conn:
            return session_move.read_subject(conn, session_uuid, need_conversation=mode != "fresh")

    try:
        subject = await run_in_threadpool(read)
    except MigrateError as exc:
        raise _http(exc) from exc
    running_op = inflight.op_for(session_uuid)
    if running_op is not None:
        raise HTTPException(409, {"code": "move_in_progress", "detail": "this session is already being moved", "op_id": running_op})
    hooks = pack_move_env.source_hooks(request.app.state)
    if mode == "move" and not stop_running and interrupt.is_running(await hooks.find(session_uuid)):
        raise HTTPException(409, {"code": "agents_running", "detail": interrupt.refusal_text([str(subject["row"].get("title") or "the agent")])})
    op_id = session_move.ops.new_id()
    add_project = await _project_adder(peer, subject["project"]["display_name"]) if with_project else None
    project = subject["project"]
    code = carry_step.CodeStep(root=project["root"], air_gap=bool(project.get("air_gap")), label=str(peer.label),
                               target_caps=peer_links.LINKS.capabilities(peer.peer_install_id) if peer_links.LINKS is not None else [],
                               carry_commits=lambda: project_transport_routes.carry_to(project, peer.peer_install_id, str(peer.label), False),
                               request=apply.guarded(request_fn), project_uid=project["uid"], outbox=env.outbox, op_id=op_id)

    async def run() -> None:
        try:
            await session_move.move_session(env, hooks, apply.guarded(request_fn), subject=subject, target_install_id=peer.peer_install_id,
                                            target_label=peer.label, op_id=op_id, wait_seconds=wait_seconds, mode=mode, add_project=add_project, stop_running=stop_running, code=code)
            await _refresh_listing(peer)
        except MigrateError as exc:
            logger.info("pack_session_move_failed", code=exc.code, step=exc.step)
        except Exception:  # noqa: BLE001
            logger.exception("pack_session_move_crashed")

    task = asyncio.get_running_loop().create_task(run())
    inflight.register(op_id, task, (session_uuid,))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"op_id": op_id, "state": "waiting", "machine": peer.label, "mode": mode}


@router.post("/sessions/{session_uuid}/move", dependencies=[Depends(require_peer_sessions)])
async def move_session(session_uuid: str, body: MoveBody, request: Request) -> Dict[str, Any]:
    """Move one running session of this computer to a paired computer, resumed in the same conversation.

    Inputs: session_uuid (the durable ``sessions.session_uuid``); body (MoveBody). Output: {op_id, state, machine}.
    Raises: 404 ``unknown_session`` / ``unknown_machine``, 409 ``session_not_movable`` / ``no_conversation`` / ``project_moved_away`` /
      ``move_in_progress`` and (from the op, on ``GET /pack/ops/{id}``) ``turn_not_ended`` / ``project_not_on_target`` / ``account_not_usable``,
      403 ``pack_restricted``, 502 ``machine_unreachable``.
    Example: POST /api/v1/sessions/0198c8f0-1111/move {"machine": "studio"}
    """
    answer = await start_send(session_uuid, body.machine, body.wait_seconds, request)
    return {k: answer[k] for k in ("op_id", "state", "machine")}

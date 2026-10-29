
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.api import pack_migrate_env as env_mod, pack_move_env
from src.api.pack_move_routes import MOVE_TIMEOUT_SECONDS, _http, start_send
from src.api.project_replica_routes import find_peer
from src.core.federation import peer_links
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.migrate import apply
from src.core.pack.migrate.plan import MigrateError
from src.core.pack.move import interrupt, session_move, turn
from src.core.pack.send import check as send_check

router = APIRouter()
pack_capabilities.register("pack.session_send")


class SendBody(BaseModel):
    """Which computer, which mode, whether to add the project there first, and how long to wait for the turn to end."""

    model_config = ConfigDict(extra="forbid")

    machine: str = Field(min_length=1, max_length=200)
    mode: Literal["move", "copy", "fresh"]
    with_project: bool = False
    wait_seconds: int = Field(default=session_move.DEFAULT_WAIT_SECONDS, ge=0, le=3600)
    stop_running: bool = Field(default=False, description="a move only: interrupt the agent if it is mid-turn (Escape), move it, then tell it to continue on the other computer; off (default) refuses the move while it is running")


class CheckBody(BaseModel):
    """Which computer to ask about."""

    model_config = ConfigDict(extra="forbid")

    machine: str = Field(min_length=1, max_length=200)
    stop_running: bool = Field(default=False, description="the same box as on /send: with it off, a mid-turn agent makes ``move`` not ok and names it")


@router.post("/sessions/{session_uuid}/send", dependencies=[Depends(require_auth)])
async def send_session(session_uuid: str, body: SendBody, request: Request) -> Dict[str, Any]:
    """
    Inputs: session_uuid (``sessions.session_uuid``); body (SendBody). Output: {op_id, state, machine, mode}.
    Raises: 404 ``unknown_session`` / ``unknown_machine``, 409 ``session_not_movable`` / ``no_conversation`` (move, copy) / ``project_moved_away`` /
      ``move_in_progress`` and, from the op on ``GET /pack/ops/{id}``, ``turn_not_ended`` / ``project_not_on_target`` (without ``with_project``) /
      ``pack_restricted`` / ``account_not_usable`` / ``launch_profile_not_on_target``; 502 ``machine_unreachable``; a ``move`` of an agent that is mid-turn is
      refused up front, 409 ``agents_running`` naming it, unless ``stop_running`` is true.
    Example: POST /api/v1/sessions/9f27394c-1111/send {"machine": "hosta", "mode": "copy", "with_project": true}
    """
    return await start_send(session_uuid, body.machine, body.wait_seconds, request, mode=body.mode, with_project=body.with_project, stop_running=body.stop_running)


@router.post("/sessions/{session_uuid}/send/check", dependencies=[Depends(require_auth)])
async def send_check_route(session_uuid: str, body: CheckBody, request: Request) -> Dict[str, Any]:
    """What sending this session to that computer would do in each mode, with no side effects.

    Output: {move, copy, fresh: {ok, reason?, detail?}, project_on_target, project_addable: {ok, reason?}, carry: {units, left_behind}, stop_shells: int, running: bool}.
      ``running`` is true while the agent is mid-turn; ``move`` is then not ok (``agents_running``) unless ``stop_running`` is true.
    Raises: 404 ``unknown_session`` / ``unknown_machine``, 409 ``session_not_movable`` / ``project_moved_away``, 502 ``machine_unreachable``.
    Example: POST /api/v1/sessions/9f27394c-1111/send/check {"machine": "hosta"}
    """
    peer = await run_in_threadpool(find_peer, body.machine)
    request_fn = env_mod.link_request(peer.peer_install_id, MOVE_TIMEOUT_SECONDS)
    if request_fn is None:
        raise HTTPException(502, {"code": "machine_unreachable", "detail": f"{peer.label} is not connected right now"})
    env = env_mod.source_env()

    def read() -> Dict[str, Any]:
        with closing(env.open_db()) as conn:
            return session_move.read_subject(conn, session_uuid, need_conversation=False)

    try:
        subject = await run_in_threadpool(read)
    except MigrateError as exc:
        raise _http(exc) from exc
    hooks = pack_move_env.source_hooks(request.app.state)
    account_key = await run_in_threadpool(hooks.account_key, session_uuid)
    answer = await send_check.check(env, apply.guarded(request_fn), subject=subject, account_key=account_key, target_install_id=peer.peer_install_id,
                                   target_label=str(peer.label), target_caps=peer_links.LINKS.capabilities(peer.peer_install_id) if peer_links.LINKS is not None else [])
    info = await hooks.find(session_uuid)
    answer["stop_shells"] = turn.shells_only(info)
    answer["running"] = interrupt.is_running(info)
    if answer["running"] and not body.stop_running and answer["move"].get("ok"):
        answer["move"] = {"ok": False, "reason": "agents_running", "detail": interrupt.refusal_text([str(subject["row"].get("title") or "the agent")])}
    return answer


from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from src.api.federation_pack_transport_routes import _peer_only, is_member
from src.api.peer_auth import Principal, require_peer
from src.core.pack.jobs import activity as pack_activity
from src.core.pack.jobs.agent_types import CAP_ACCOUNT_IDENTITY, CAP_AGENT_AGY, CAP_REPLY_DIGEST
from src.core.pack.jobs.host import Host
from src.core.pack.jobs.types import CAP_AGENT, CAP_JOBS, AdmitBody, JobError, JobIdBody, LookBody, ReplyBody, StartBody, StopBody
from src.core.pack.machines import capabilities as pack_capabilities
from src.api.error_response import refusal_error

router = APIRouter(prefix="/federation/pack/jobs", tags=["federation"])
_require_replica = require_peer("replica")
pack_capabilities.register(CAP_JOBS, CAP_AGENT, CAP_AGENT_AGY, CAP_REPLY_DIGEST, CAP_ACCOUNT_IDENTITY, pack_activity.CAP_ACTIVITY)


def _mesh_only() -> None:
    if not pack_capabilities.mesh_on():
        raise HTTPException(404, "Not Found")


async def _call(request: Request, principal: Principal, verb: Callable[[Host, str], Awaitable[Any]]) -> Any:
    caller = _peer_only(principal)
    host = getattr(request.app.state, "pack_jobs_host", None)
    if host is None:
        raise HTTPException(503, {"code": "jobs_not_ready", "detail": "this computer is not ready to run jobs yet"})
    try:
        return await verb(host, caller)
    except JobError as exc:
        raise refusal_error(exc) from exc


@router.post("/admit")
async def admit(body: AdmitBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Could this computer run a job of this kind now? Output: {ok: true}. Raises 403, 409 project_not_here, 503 host_busy."""
    return await _call(request, principal, lambda h, c: h.admit(c, body, member=is_member(principal)))


@router.post("/start")
async def start(body: StartBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Verify the snapshot blob and start preparing the folder. Output: {ok: true, state: "preparing"}. Raises 409 bundle_unverified."""
    return await _call(request, principal, lambda h, c: h.start(c, body, member=is_member(principal)))


@router.post("/status")
async def status(body: JobIdBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """The job's state, exit code and the tail of its output. Output: StatusAnswer."""
    return await _call(request, principal, lambda h, c: h.status(c, body))


@router.post("/collect")
async def collect(body: JobIdBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Gather the result and send its bundle back (repeatable). Output: CollectAnswer. Raises 409 still_running."""
    return await _call(request, principal, lambda h, c: h.collect(c, body))


@router.post("/stop")
async def stop(body: StopBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Stop the job, optionally keeping its folder for a day. Output: {ok: true}."""
    return await _call(request, principal, lambda h, c: h.stop(c, body))


@router.post("/release")
async def release(body: JobIdBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Free the folder and delete the job's run files. Output: {ok: true}."""
    return await _call(request, principal, lambda h, c: h.release(c, body))


@router.post("/reply")
async def reply(body: ReplyBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Type the asking session's answer into the parked worker of an agent job. Output: {ok: true}. Raises 409 not_asking, owner_only, worker_not_ready."""
    return await _call(request, principal, lambda h, c: h.reply(c, body))


@router.get("/activity")
async def get_peer_activity(request: Request, days: int = Query(7, ge=1, le=30), limit: int = Query(100, ge=1, le=200),
                            principal: Principal = Depends(_require_replica)) -> Any:
    """Read-only summary of jobs this computer sent in the last ``days`` days so peers can show Pack-wide activity (#3328)."""
    _peer_only(principal)
    host = getattr(request.app.state, "pack_jobs_host", None)
    if host is None:
        raise HTTPException(503, {"code": "jobs_not_ready", "detail": "this computer is not ready to run jobs yet"})
    return await run_in_threadpool(lambda: pack_activity.local_peer_jobs(host.store, host.store.state_dir, days=days, limit=limit))


@router.post("/look", include_in_schema=False, dependencies=[Depends(_mesh_only)])
async def look(request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """A reduced snapshot of this computer (room and capability facts) and whether it would take work of this project from the caller.

    Output: {snapshot, project}. Raises 404 (switch off, before auth and before the body is read), 403, 422 (a bad body, only while the switch is on).
    """
    try:
        body = LookBody.model_validate(await request.json())
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, {"code": "bad_request", "detail": "the look needs a JSON body with a project_uid"}) from exc
    return await _call(request, principal, lambda h, c: h.look(c, body.project_uid))

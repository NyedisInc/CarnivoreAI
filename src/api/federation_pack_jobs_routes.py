
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.federation_pack_transport_routes import _peer_only
from src.api.peer_auth import Principal, require_peer
from src.core.pack.jobs.agent_types import CAP_ACCOUNT_IDENTITY, CAP_REPLY_DIGEST
from src.core.pack.jobs.host import Host
from src.core.pack.jobs.types import CAP_AGENT, CAP_JOBS, AdmitBody, JobError, JobIdBody, ReplyBody, StartBody, StopBody
from src.core.pack.machines import capabilities as pack_capabilities
from src.api.error_response import refusal_error

router = APIRouter(prefix="/federation/pack/jobs", tags=["federation"])
_require_replica = require_peer("replica")
pack_capabilities.register(CAP_JOBS, CAP_AGENT, CAP_REPLY_DIGEST, CAP_ACCOUNT_IDENTITY)


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
    return await _call(request, principal, lambda h, c: h.admit(c, body))


@router.post("/start")
async def start(body: StartBody, request: Request, principal: Principal = Depends(_require_replica)) -> Any:
    """Verify the snapshot blob and start preparing the folder. Output: {ok: true, state: "preparing"}. Raises 409 bundle_unverified."""
    return await _call(request, principal, lambda h, c: h.start(c, body))


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

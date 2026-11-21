
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.federation_pack_transport_routes import _peer_only
from src.api.peer_auth import Principal, require_peer
from src.core.pack.jobs.install import CAP_INSTALL, MAX_TOOLS, Installer
from src.core.pack.jobs.types import JOB_ID_PATTERN, JobError
from src.core.pack.machines import capabilities as pack_capabilities
from src.api.error_response import refusal_error

router = APIRouter(prefix="/federation/pack/jobs/install", tags=["federation"])
_require_replica = require_peer("replica")
pack_capabilities.register(CAP_INSTALL)


class InstallBody(BaseModel):
    """Which tools one approved job wants installed first."""

    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(pattern=JOB_ID_PATTERN)
    project_uid: str = Field(min_length=1, max_length=64)
    tools: List[str] = Field(min_length=1, max_length=MAX_TOOLS)


def _parts(request: Request) -> "tuple[Any, Installer]":
    host, installer = (getattr(request.app.state, n, None) for n in ("pack_jobs_host", "pack_jobs_installer"))
    if host is None or installer is None:
        raise HTTPException(503, {"code": "jobs_not_ready", "detail": "this computer is not ready to run jobs yet"})
    return host, installer


async def _guard(call: Callable[[], Any]) -> Any:
    try:
        return await call()
    except JobError as exc:
        raise refusal_error(exc) from exc


@router.post("")
async def request_install(body: InstallBody, request: Request, principal: Principal = Depends(_require_replica)) -> Dict[str, Any]:
    """Queue the Homebrew installs for an approved job. Output: {installs: [{id, tool, state, ...}]}. Raises 403, 404, 409 no_brew, 422, 429."""
    caller = _peer_only(principal)
    host, installer = _parts(request)

    async def run() -> Dict[str, Any]:
        await asyncio.to_thread(host._gate_sync, caller, body.project_uid)  # noqa: SLF001
        rows = await installer.request(caller, body.job_id, body.tools)
        return {"installs": [r.public() for r in rows]}

    return await _guard(run)


@router.get("/{install_id}")
async def install_status(request: Request, principal: Principal = Depends(_require_replica),
                         install_id: str = Path(pattern=r"^ins_[0-9a-f]{12}$")) -> Dict[str, Any]:
    """One install of the calling computer. Output: {id, tool, state, started_at, ended_at, exit_code, tail}. Raises 404 unknown_install."""
    caller = _peer_only(principal)
    _host, installer = _parts(request)

    async def run() -> Dict[str, Any]:
        return (await asyncio.to_thread(installer.status, caller, install_id)).public()

    return await _guard(run)


from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, StrictStr

from src.api.auth import require_auth, security
from src.api.error_response import api_error, refusal_error
from src.core.api_keys.store import is_api_key
from fastapi.security import HTTPAuthorizationCredentials
from src.core.pack.jobs import install as install_mod
from src.core.pack.jobs.types import JobError

router = APIRouter(prefix="/pack/installs", tags=["pack-jobs"], dependencies=[Depends(require_auth)])


class InstallToolBody(BaseModel):
    """The one tool to install."""

    model_config = ConfigDict(extra="forbid")
    tool: StrictStr


async def _owner_only(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> None:
    if credentials is not None and is_api_key(credentials.credentials):
        raise api_error(403, "install_owner_only")


def _installer(request: Request) -> install_mod.Installer:
    installer = getattr(request.app.state, "pack_jobs_installer", None)
    if installer is None:
        raise api_error(503, "jobs_not_ready")
    return installer


@router.get("")
async def list_installs(request: Request, limit: int = 50) -> Dict[str, Any]:
    """Output: {installs: [...], allow: {tool: true}, can_install: bool}. Raises 503 jobs_not_ready."""
    installer = _installer(request)
    rows = await asyncio.to_thread(installer.rows, limit)
    return {"installs": [r.public() for r in rows], "allow": sorted(install_mod.ALLOW), "can_install": await asyncio.to_thread(installer.can_install)}


@router.post("", dependencies=[Depends(_owner_only)])
async def install_tool(body: InstallToolBody, request: Request) -> Dict[str, Any]:
    """Install one allow-listed tool on this computer. Output: {installs: [row]}. Raises 403 pack_restricted, 409 no_brew, 422 tool_not_allowed, 429."""
    installer = _installer(request)
    try:
        rows = await installer.request("owner", "", [body.tool], owner=True)
    except JobError as exc:
        raise refusal_error(exc) from exc
    return {"installs": [r.public() for r in rows]}

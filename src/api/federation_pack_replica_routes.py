
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from src.api import projects_service
from src.api.peer_auth import Principal, require_peer
from src.config import settings
from src.core.pack.identity import home, replicas
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.trust_carry import wire as trust_wire

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack", tags=["federation"])

_require_replica = require_peer("replica")

pack_capabilities.register("pack.replica", "pack.identity", trust_wire.CAP_TRUST_CARRY, trust_wire.CAP_IMPORTS_CARRY)


class ReplicaBody(BaseModel):

    model_config = ConfigDict(extra="forbid")

    project_uid: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    root: Optional[str] = Field(default=None, max_length=1024)
    company_uid: Optional[str] = Field(default=None, max_length=64)
    company_name: Optional[str] = Field(default=None, max_length=200)
    transport: Optional[str] = Field(default=None, max_length=32)
    source_trusted: bool = False
    source_imports_ok: bool = False


def _peer_only(principal: Principal) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer registers a replica"})
    return principal.grant.peer_install_id


@router.post("/replica")
async def register_replica(body: ReplicaBody, principal: Principal = Depends(_require_replica)) -> Dict[str, Any]:
    """
    Inputs: body (ReplicaBody). Output: {project_uid, project_id, name, root, state, created}.
    Raises: HTTPException 403 not a peer, 409 ``project_uid_is_home`` or ``project_name_taken``.
    """
    home_install_id = _peer_only(principal)

    def write() -> Dict[str, Any]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            try:
                answer = replicas.accept_replica(conn, home_install_id=home_install_id, project_uid=body.project_uid,
                                                 name=body.name, root=body.root, company_uid=body.company_uid,
                                                 company_name=body.company_name, source_trusted=body.source_trusted, source_imports_ok=body.source_imports_ok)
            except replicas.ReplicaRefused as exc:
                raise HTTPException(exc.status, {"code": exc.code, "detail": str(exc)}) from exc
            home.notify_changed()
            return answer

    logger.info("pack_replica_registered", project_uid=body.project_uid, home=home_install_id)
    return await run_in_threadpool(write)


@router.delete("/replica/{project_uid}")
async def detach_replica(project_uid: str, principal: Principal = Depends(_require_replica)) -> Dict[str, Any]:
    """
    Inputs: project_uid (str). Output: {detached: bool} (False when there was nothing to detach, never an error).
    Raises: HTTPException 403 not a peer.
    """
    home_install_id = _peer_only(principal)

    def write() -> Dict[str, Any]:
        with closing(projects_service.open_db_or_503(settings)) as conn:
            done = replicas.detach_replica(conn, home_install_id=home_install_id, project_uid=project_uid)
            if done:
                home.notify_changed()
            return {"detached": done}

    return await run_in_threadpool(write)

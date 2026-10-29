
from __future__ import annotations

from contextlib import closing
from typing import Annotated, Any, Callable, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from src.api import pack_migrate_env as env_mod
from src.api.peer_auth import Principal, require_peer
from src.core.pack.identity import home
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.migrate import apply, ops, plan, receive, task_manager_side
from src.core.pack.trust_carry import wire as trust_wire

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack/migrate", tags=["federation"])
_require_migrate = require_peer("migrate")
pack_capabilities.register("pack.migrate", trust_wire.CAP_TRUST_CARRY, trust_wire.CAP_IMPORTS_CARRY, task_manager_side.CAP_TASK_FILES_PLAN)

_OP = Field(min_length=3, max_length=64)


class PrepareBody(BaseModel):
    """What the sender wants to move and how much room it needs."""

    model_config = ConfigDict(extra="forbid")

    op_id: str = _OP
    project_uid: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="project", pattern="^(project|company)$")
    root_hint: Optional[str] = Field(default=None, max_length=1024)
    company_uid: Optional[str] = Field(default=None, max_length=64)
    bytes_needed: int = Field(default=0, ge=0)
    source_trusted: bool = False
    source_imports_ok: bool = False
    parent_id: Optional[str] = Field(default=None, max_length=64)
    dry_run: bool = False
    task_file_parts: List[Annotated[str, StringConstraints(max_length=task_manager_side.MAX_PART_CHARS)]] = Field(default_factory=list, max_length=task_manager_side.MAX_PROBED_PARTS)


class CodeBody(BaseModel):
    """The code step's facts: the rung's inputs and the sealed blob (none for rung ``git``)."""

    model_config = ConfigDict(extra="forbid")

    branch: Optional[str] = Field(default=None, max_length=300)
    head: Optional[str] = Field(default=None, max_length=64)
    remote: Optional[str] = Field(default=None, max_length=500)
    stats: Optional[Dict[str, int]] = None
    blob_id: Optional[str] = Field(default=None, max_length=64)


class ReceiveBody(BaseModel):
    """Everything sent for one op, by blob id."""

    model_config = ConfigDict(extra="forbid")

    op_id: str = _OP
    rung: str = Field(pattern="^(git|carried|tar|units)$")
    code: CodeBody = CodeBody()
    manifest_blob_id: str = Field(max_length=64)
    transcripts_blob_id: Optional[str] = Field(default=None, max_length=64)
    air_gap: bool = False
    source_root: Optional[str] = Field(default=None, max_length=1024)


class OpBody(BaseModel):
    """A step that only names the op."""

    model_config = ConfigDict(extra="forbid")

    op_id: str = _OP


class BackBody(BaseModel):
    """The project (by uid) the caller wants returned, under the op id the caller follows."""

    model_config = ConfigDict(extra="forbid")

    op_id: str = _OP
    project_uid: str = Field(min_length=8, max_length=64)


def _peer_only(principal: Principal) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer drives a migrate"})
    return principal.grant.peer_install_id


async def _step(fn: Callable[..., Dict[str, Any]], principal: Principal, body: BaseModel) -> Dict[str, Any]:
    sender = _peer_only(principal)
    data = body.model_dump()

    def run() -> Dict[str, Any]:
        return fn(env_mod.target_env(), sender, data)

    try:
        return await run_in_threadpool(run)
    except receive.MigrateRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": exc.detail, "rule": exc.rule}) from exc


@router.post("/prepare")
async def prepare(body: PrepareBody, principal: Principal = Depends(_require_migrate)) -> Dict[str, Any]:
    """Whether this machine takes the project and where. Output: {root, case, project_id, free_bytes}. Raises 403 ``pack_restricted`` and the refusals of ``receive.prepare``."""
    return await _step(receive.prepare, principal, body)


@router.post("/receive")
async def receive_op(body: ReceiveBody, principal: Principal = Depends(_require_migrate)) -> Dict[str, Any]:
    """Bring the project in as a replica; undone on any failure. Output: {summary, written, root}."""
    return await _step(receive.receive, principal, body)


@router.post("/verify")
async def verify(body: OpBody, principal: Principal = Depends(_require_migrate)) -> Dict[str, Any]:
    """Check it all arrived. Output: {ok, misses}."""
    return await _step(receive.verify, principal, body)


@router.post("/flip")
async def flip(body: OpBody, principal: Principal = Depends(_require_migrate)) -> Dict[str, Any]:
    """Become the home of the verified project. Output: {flipped, root, reinstall_failed}."""
    return await _step(receive.flip, principal, body)


@router.post("/abort")
async def abort(body: OpBody, principal: Principal = Depends(_require_migrate)) -> Dict[str, Any]:
    """Remove what this op made (idempotent; refused once flipped). Output: {aborted}."""
    return await _step(receive.abort, principal, body)


def _came_from(project_uid: str, sender: str) -> Optional[Dict[str, Any]]:
    with closing(env_mod.source_env().open_db()) as conn:
        project = conn.execute("SELECT * FROM projects WHERE uid = ?", (project_uid,)).fetchone()
        if project is None or project["pack_state"] != home.HOME:
            return None
        arrived = conn.execute("SELECT 1 FROM pack_migrations WHERE subject_uid = ? AND role = 'target' AND source_install_id = ? AND state = 'flipped'",
                               (project_uid, sender)).fetchone()
        return dict(project) if arrived else None


@router.post("/back")
async def move_back(body: BackBody, principal: Principal = Depends(_require_migrate)) -> Dict[str, Any]:
    """The machine this project came from asks for it back: plan and apply a migrate to it right now, under the caller's op id.

    Output: the flip answer. Raises 404 ``not_moved_from_you`` (not home here, or it did not arrive from the caller), 409/502 as a migrate.
    """
    sender = _peer_only(principal)
    project = await run_in_threadpool(_came_from, body.project_uid, sender)
    if project is None:
        raise HTTPException(404, {"code": "not_moved_from_you", "detail": "this computer is not holding a project that came from you"})
    request = env_mod.link_request(sender)
    if request is None:
        raise HTTPException(502, {"code": "machine_unreachable", "detail": "this computer cannot reach you right now"})
    env = env_mod.source_env()
    try:
        made = await plan.plan_project(env, project, sender, apply.guarded(request))
        if made.blocking:
            raise plan.MigrateError("blocked", "; ".join(c["detail"] for c in made.checks if c["name"] in made.blocking), 409)
        return await apply.apply_project(env, made, request, op_id=body.op_id)
    except plan.MigrateError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": exc.detail, "step": exc.step, "rule": exc.rule}) from exc

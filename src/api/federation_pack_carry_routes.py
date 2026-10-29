
from __future__ import annotations

import re
from contextlib import closing
from typing import Any, Dict, List, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.api import pack_migrate_env as env_mod
from src.api.peer_auth import Principal, require_peer
from src.config import settings
from src.core import project_worktree
from src.core.pack.carry import land, scan, wip, worktree
from src.core.pack.identity import home, replicas
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.migrate.receive import MigrateRefused, check_allowed
from src.core.pack.transport import blobs

logger = structlog.get_logger()
router = APIRouter(prefix="/federation/pack/carry", tags=["federation"])
_require_migrate = require_peer("migrate")
pack_capabilities.register(scan.CARRY_TREE)

_SHA = r"^[0-9a-f]{40,64}$"
_TOOL = re.compile(r"^[A-Za-z0-9._+-]{1,40}$")


class CheckUnit(BaseModel):
    """One repo unit to ask about."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["repo"]
    rel: str = Field(min_length=1, max_length=1024)
    head: str = Field(pattern=_SHA)


class CheckBody(BaseModel):
    """Dry run: nothing is written."""

    model_config = ConfigDict(extra="forbid")

    project_uid: str = Field(min_length=8, max_length=64)
    units: List[CheckUnit] = Field(default=[], max_length=200)
    which: List[str] = Field(default=[], max_length=50)

    @field_validator("which")
    @classmethod
    def _names(cls, value: List[str]) -> List[str]:
        if any(not _TOOL.match(n) for n in value):
            raise ValueError("bad tool name")
        return value


class Unit(BaseModel):
    """One unit to land: a git repo (``rel`` is its folder under the project root, "." for the root repo) or the loose files (``rel`` ".")."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["repo", "files", "worktree"]
    rel: str = Field(min_length=1, max_length=1024)
    blob_id: Optional[str] = Field(default=None, max_length=64)
    src: Optional[str] = Field(default=None, max_length=1024, pattern=r"^/[^\x00]*$")
    home_rel: Optional[str] = Field(default=None, max_length=1024, pattern=r"^[^/\x00][^\x00]*$")
    branch: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}$")
    head: Optional[str] = Field(default=None, pattern=_SHA)
    commits: bool = True
    wip: Optional[str] = Field(default=None, pattern=_SHA)
    index: Optional[str] = Field(default=None, pattern=_SHA)
    remote: Optional[str] = Field(default=None, max_length=500, pattern=land.REMOTE_RE.pattern)

    @model_validator(mode="after")
    def _shape(self) -> "Unit":
        if self.kind != "files" and (not self.head or bool(self.wip) != bool(self.index) or (self.kind == "repo" and not self.branch)):
            raise ValueError("a repo unit needs branch and head, and wip with index")
        if self.kind == "worktree" and not self.src:
            raise ValueError("a worktree unit names its source path")
        if not self.blob_id and (self.kind == "files" or self.wip or (self.kind == "repo" and self.commits)):
            raise ValueError("this unit carries a blob")
        if self.kind == "files" and self.rel != ".":
            raise ValueError("loose files land at the project root")
        return self


class ApplyBody(BaseModel):
    """One unit of one op."""

    model_config = ConfigDict(extra="forbid")

    op_id: str = Field(pattern=r"^[A-Za-z0-9_-]{3,64}$")
    project_uid: str = Field(min_length=8, max_length=64)
    unit: Unit


def _project(project_uid: str, sender: str) -> Dict[str, Any]:
    env = env_mod.target_env()
    check_allowed(env, project_uid, None)
    with closing(env.open_db()) as conn:
        row = conn.execute("SELECT * FROM projects WHERE uid = ?", (project_uid,)).fetchone()
    if row is not None and row["company_id"] is not None:
        with closing(env.open_db()) as conn:
            company = conn.execute("SELECT uid FROM companies WHERE id = ?", (row["company_id"],)).fetchone()
        check_allowed(env, project_uid, company["uid"] if company else None)
    if row is None or row["archived_at"] is not None:
        raise MigrateRefused("project_not_on_target", "this computer does not hold that project yet; make a replica of it here first")
    if row["pack_state"] == home.MOVED_AWAY:
        raise MigrateRefused("project_moved_away", "that project moved away from this computer")
    with closing(env.open_db()) as conn:
        counterparts = {r["install_id"] for r in replicas.list_replicas(conn, project_uid)} if row["pack_state"] == home.HOME else {row["home_install_id"]}
    if sender not in counterparts:
        raise MigrateRefused("not_a_counterpart", "that computer is neither this project's home nor its replica", 403)
    return dict(row)


def _peer(principal: Principal) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required", "detail": "only a paired computer carries a folder"})
    return principal.grant.peer_install_id


def _refuse(exc: MigrateRefused) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "detail": exc.detail, "rule": exc.rule})


@router.post("/check")
async def check(body: CheckBody, principal: Principal = Depends(_require_migrate)) -> Dict[str, Any]:
    """Dry run per unit. Output: {units: [{present, has_head, behind, own_changes, diverged}], which: {name: bool}}. Writes nothing.

    Raises: 403 ``pack_restricted`` / ``peer_token_required``, 409 ``project_not_on_target`` / ``project_moved_away``, 422 ``unsafe_path``.
    """
    sender = _peer(principal)

    def run() -> Dict[str, Any]:
        project = _project(body.project_uid, sender)
        air = bool(project.get("air_gap"))
        return {"units": [land.check_unit(project["root"], u.model_dump(), air_gap=air) for u in body.units], "which": land.which(body.which)}

    try:
        return await run_in_threadpool(run)
    except MigrateRefused as exc:
        raise _refuse(exc) from exc


@router.post("/apply")
async def apply(body: ApplyBody, principal: Principal = Depends(_require_migrate)) -> Dict[str, Any]:
    """Land one sealed unit into the project's folder here, then delete the blob. Output: {head, restored} (a repo) or {placed} (loose files).

    Raises: 403 ``pack_restricted`` / ``peer_token_required`` / ``not_a_counterpart``, 404 ``unknown_blob``, 409 ``project_not_on_target`` / ``target_has_own_changes`` /
      ``bundle_unverified`` / ``bundle_apply_failed``, 422 ``unsafe_path`` / ``unsafe_archive``, 507 ``carry_too_large``.
    """
    sender = _peer(principal)
    inbox = env_mod.target_env().inbox
    unit = body.unit.model_dump()

    def run() -> Dict[str, Any]:
        project = _project(body.project_uid, sender)
        landed = land.unit_dir(project["root"], unit["rel"])
        blob = None
        if unit["blob_id"]:
            try:
                blob = str(inbox.sealed_path(unit["blob_id"], peer=sender))
            except blobs.BlobError as exc:
                raise MigrateRefused(exc.code, "that blob is not here for this computer", exc.status) from exc
        air = bool(project.get("air_gap"))
        if unit["kind"] == "files":
            answer: Dict[str, Any] = {"placed": land.apply_files(project["root"], blob)}
        elif unit["kind"] == "worktree":
            answer = worktree.apply_worktree(project["root"], unit, blob, wip.ref_name(body.op_id, "wt:" + unit["src"]),
                                             project_worktree.read_root(settings.auth_config_file), air_gap=air)
        else:
            answer = land.apply_repo(project["root"], sender, unit, blob, wip.ref_name(body.op_id, unit["rel"]), air_gap=air)
        if unit["blob_id"]:
            inbox.remove(unit["blob_id"])
        if unit["src"] and "paths" not in answer:
            answer = {**answer, "path": landed, "paths": {unit["src"]: landed}}
        return answer

    logger.info("pack_carry_apply", project_uid=body.project_uid, kind=body.unit.kind, sender=sender)
    try:
        return await run_in_threadpool(run)
    except MigrateRefused as exc:
        raise _refuse(exc) from exc

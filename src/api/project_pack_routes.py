
from __future__ import annotations

import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from src.api import projects_service
from src.api.auth import require_auth
from src.api.project_move_routes import read_live_panes
from src.config import settings
from src.core.project_move.fingerprint import FingerprintError, require_quoted
from src.core.project_pack import integrity, jobs, recover, store
from src.core.project_pack import constants as K
from src.core.project_pack.env import PackEnv
from src.core.project_pack.pack import run_pack
from src.core.project_pack.plan import PackPlan
from src.core.project_pack.plan_pack import build_pack_plan
from src.core.project_pack.plan_unpack import build_unpack_plan
from src.core.project_pack.unpack import run_unpack
from src.core.project_pack.view import storage_view
from src.models.project_pack import (
    ProjectPackRequest,
    ProjectPackResponse,
    ProjectStorageResponse,
    ProjectUnpackRequest,
    ProjectVerifyResponse,
)

logger = structlog.get_logger()
router = APIRouter()


def make_env() -> PackEnv:
    return PackEnv(state_dir=Path(settings.get_state_dir()))


def _open_conn():
    return projects_service.open_db_or_503(settings)


def _response(plan: PackPlan, job: Any = None) -> ProjectPackResponse:
    return ProjectPackResponse(**plan.as_dict(), job=job)


def _apply(plan: PackPlan, quoted: Any, runner: Callable[..., None], env: PackEnv) -> ProjectPackResponse:
    try:
        require_quoted(plan, quoted)
    except FingerprintError as exc:
        raise HTTPException(status_code=exc.status, detail={"message": str(exc), "plan": _response(plan).model_dump()})
    if not plan.ok:
        raise HTTPException(status_code=409, detail={
            "message": "refused: " + "; ".join(plan.failed()), "plan": _response(plan).model_dump()})
    job_id = uuid.uuid4().hex[:8]
    try:
        progress = jobs.start(plan.project["id"], lambda p: runner(_open_conn, plan, env, p, job_id))
    except jobs.JobBusy as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc)})
    logger.info("project_pack_job_started", kind=plan.kind, project_id=plan.project["id"], job_id=job_id)
    return _response(plan, {"id": job_id, "kind": plan.kind, "progress": progress.as_dict()})


def _pack(project_name: str, body: ProjectPackRequest) -> ProjectPackResponse:
    panes, env = read_live_panes(), make_env()
    with closing(_open_conn()) as conn:
        project = projects_service.resolve_target(conn, project_name)
        plan = build_pack_plan(conn, dict(project), panes=panes, env=env, accept_local_only=body.accept_local_only)
        return _apply(plan, body.plan_fingerprint, run_pack, env) if body.apply else _response(plan)


def _unpack(project_name: str, body: ProjectUnpackRequest) -> ProjectPackResponse:
    env = make_env()
    with closing(_open_conn()) as conn:
        project = projects_service.resolve_target(conn, project_name)
        plan = build_unpack_plan(conn, dict(project), env=env)
        return _apply(plan, body.plan_fingerprint, run_unpack, env) if body.apply else _response(plan)


@router.post("/projects/{project_name}/pack", response_model=ProjectPackResponse, dependencies=[Depends(require_auth)])
async def pack_project(project_name: str, body: ProjectPackRequest) -> ProjectPackResponse:
    """Plan or start packing a hidden project's folder into one archive inside it.

    Description: ``apply`` false answers the plan (every check named, sizes, git report, children, estimate,
      ``fingerprint``) and changes nothing. ``apply`` true quotes that ``plan_fingerprint``; a fresh plan must still
      pass; the job then runs on a worker thread (originals go to the Trash only after the archive is verified
      against a per-file sha256 manifest). Refused for a project that is not hidden, has a live session, an
      unpushed or dirty git repo, cloud-only files or too little free space.
    Inputs: project_name (str, URL); body (ProjectPackRequest).
    Output: ProjectPackResponse - the plan; ``job`` set once an apply started.
    Raises: HTTPException 404 unknown project, 428 apply without a fingerprint, 412 a stale one, 409 ambiguous
      name, a refused plan or another job running, 503 database unreachable or read-only.
    """
    if body.apply:
        projects_service.guard_writable(settings)
    return await run_in_threadpool(_pack, project_name, body)


@router.post("/projects/{project_name}/unpack", response_model=ProjectPackResponse, dependencies=[Depends(require_auth)])
async def unpack_project(project_name: str, body: ProjectUnpackRequest) -> ProjectPackResponse:
    """Plan or start unpacking a packed project's folder back to its files.

    Description: the plan carries a WARNING when the archive's size or modified time no longer matches what
      Carnivore stored (changed outside Carnivore). ``apply`` true quotes ``plan_fingerprint``; the job checks the
      archive's full sha256 against the database and the sidecar first and refuses a mismatch, extracts beside,
      verifies every file against the manifest, swaps the files in, then sends the archive, manifest and README
      to the Trash.
    Inputs: project_name (str, URL); body (ProjectUnpackRequest).
    Output: ProjectPackResponse. Raises: as ``pack_project``.
    """
    if body.apply:
        projects_service.guard_writable(settings)
    return await run_in_threadpool(_unpack, project_name, body)


def _storage(project_name: str, full: bool) -> Any:
    with closing(_open_conn()) as conn:
        project = projects_service.resolve_target(conn, project_name)
        row = store.get(conn, project["id"])
    if row is None:
        return project, None, None
    view = storage_view(row, project["root"], jobs.progress_of(project["id"]))
    verdict = None
    if full:
        if row["state"] != K.STATE_PACKED:
            raise HTTPException(status_code=409, detail={"message": f"the project is {row['state']}, not packed"})
        verdict = integrity.full_check(project["root"], row).as_dict()
        view["integrity"] = verdict
    return project, view, verdict


@router.get("/projects/{project_name}/storage", response_model=ProjectStorageResponse, dependencies=[Depends(require_auth)])
async def get_project_storage(project_name: str) -> ProjectStorageResponse:
    """The project's pack state, job progress and the cheap archive check (size and mtime; no file is read).

    Output: ProjectStorageResponse - ``storage`` null when the project was never packed.
    Raises: HTTPException 404 / 409 (name) / 503.
    """
    project, view, _ = await run_in_threadpool(_storage, project_name, False)
    return ProjectStorageResponse(project_id=project["id"], project_name=project["display_name"], storage=view)


@router.post("/projects/{project_name}/storage/verify", response_model=ProjectVerifyResponse,
             dependencies=[Depends(require_auth)])
async def verify_project_storage(project_name: str) -> ProjectVerifyResponse:
    """Hash the packed archive and compare it to the checksum stored when it was packed (reads the whole file).

    Output: ProjectVerifyResponse - ``integrity.status`` ok, or modified / missing / cloud_only.
    Raises: HTTPException 409 when the project is not packed.
    """
    project, view, verdict = await run_in_threadpool(_storage, project_name, True)
    return ProjectVerifyResponse(project_id=project["id"], project_name=project["display_name"], integrity=verdict,
                                 storage=view)


def recover_interrupted_jobs() -> dict:
    try:
        with closing(_open_conn()) as conn:
            return recover.recover_all(conn, make_env())
    except HTTPException as exc:
        logger.warning("project_pack_recover_skipped", detail=str(exc.detail))
        return {}

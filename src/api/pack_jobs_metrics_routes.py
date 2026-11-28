
from __future__ import annotations

import time
from contextlib import closing
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field

from src.api import projects_service
from src.api.auth import require_auth, security
from src.api.error_response import api_error, refusal_error
from src.config import settings
from src.core.api_keys.store import is_api_key
from src.core.pack.errors.input_error import PackInputError
from src.core.pack.jobs import activity as pack_activity, boot, load_report, load_store, metrics, policy
from src.core.pack.jobs.types import JobError

router = APIRouter(tags=["pack-jobs"], dependencies=[Depends(require_auth)])


class LoadProfilesBody(BaseModel):
    """Owner overrides for learned command shapes and local-only script globs of a project (#3325)."""

    model_config = ConfigDict(extra="forbid")

    reset_shape: Optional[str] = Field(default=None, max_length=120)
    reset_all: bool = False
    shape_overrides: Optional[Dict[str, Optional[Literal["local_only", "always_offload"]]]] = Field(default=None)
    local_only: Optional[List[str]] = Field(default=None, max_length=50)


def _report(days: int) -> Dict[str, Any]:
    try:
        store = boot.engine().store
    except JobError as exc:
        raise refusal_error(exc) from exc
    return metrics.report(store, days, now=time.time())


def _load_report(days: int) -> Dict[str, Any]:
    try:
        store = boot.engine().store
    except JobError as exc:
        raise refusal_error(exc) from exc
    return load_report.build(store, days, now=time.time())


@router.get("/pack/jobs/metrics")
async def get_metrics(days: int = Query(7, ge=1, le=metrics.KEEP_DAYS)) -> Dict[str, Any]:
    """P3, R3 and the last 24 load hours of this computer. Raises 422 for ``days`` outside 1..30, 503 jobs_not_ready."""
    return await run_in_threadpool(_report, days)


@router.get("/pack/load/report")
async def get_load_report(days: int = Query(7, ge=1, le=metrics.KEEP_DAYS)) -> Dict[str, Any]:
    """Pack-wide CPU/RAM utilization, idle-while-pegged waste, mirror overhead efficiency, guard funnel and learned profiles."""
    return await run_in_threadpool(_load_report, days)


@router.get("/pack/activity")
async def get_pack_activity(days: int = Query(7, ge=1, le=metrics.KEEP_DAYS),
                            limit: int = Query(250, ge=1, le=500),
                            include_peers: bool = Query(True)) -> Dict[str, Any]:
    """Pack-wide live distribution and historical activity of all agents and jobs across every computer (#3328)."""
    try:
        store = boot.engine().store
    except JobError as exc:
        raise refusal_error(exc) from exc
    return await pack_activity.build_activity(store, store.state_dir, days=days, limit=limit, include_peers=include_peers)


def _put_load_profiles(project_name: str, body: LoadProfilesBody) -> Dict[str, Any]:
    try:
        store = boot.engine().store
    except JobError as exc:
        raise refusal_error(exc) from exc
    with closing(projects_service.open_db_or_503(settings)) as conn:
        project = projects_service.resolve_target(conn, project_name)
    uid = project.get("uid")
    if not uid:
        raise api_error(409, "no_project_uid")
    cleared = 0
    if body.reset_all:
        cleared = load_store.reset_shape_runs(store, uid, None)
    elif body.reset_shape:
        cleared = load_store.reset_shape_runs(store, uid, body.reset_shape)
    if body.shape_overrides is not None:
        if len(body.shape_overrides) > 50:
            raise api_error(422, "too_many_overrides")
        for sh, mode in body.shape_overrides.items():
            if not sh or len(sh) > 120:
                raise api_error(422, "bad_shape")
            load_store.shape_override_set(store, uid, sh, mode)
    if body.local_only is not None:
        try:
            policy.set_lists(store, uid, local_only=body.local_only)
        except PackInputError as exc:
            raise api_error(422, "bad_local_only", exc) from exc
    pol = policy.get(store, uid)
    return {
        "project": project["display_name"],
        "project_uid": uid,
        "cleared_runs": cleared,
        "local_only": pol.local_only,
        "overrides": load_store.shape_overrides_list(store, uid),
    }


@router.put("/projects/{project_name}/load-profiles")
async def put_load_profiles(project_name: str, body: LoadProfilesBody,
                            credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    """Owner-only route to reset or pin learned command shapes and update a project's ``local_only`` patterns."""
    if credentials is not None and is_api_key(credentials.credentials):
        raise api_error(403, "mark_owner_only")
    return await run_in_threadpool(_put_load_profiles, project_name, body)

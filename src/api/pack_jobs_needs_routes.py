
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials

from src.api import projects_service
from src.api.auth import require_auth, security
from src.api.error_response import api_error, refusal_error
from src.config import settings
from src.core.api_keys.store import is_api_key
from src.core.pack.jobs import boot, needs_policy
from src.core.pack.jobs.types import JobError
from src.core.pack.placement import needs as needs_mod

router = APIRouter(tags=["pack-jobs"], dependencies=[Depends(require_auth)])


async def _owner_only(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> None:
    if credentials is not None and is_api_key(credentials.credentials):
        raise api_error(403, "needs_owner_only")


def _uid(name: str) -> str:
    with closing(projects_service.open_db_or_503(settings)) as conn:
        return str(projects_service.resolve_target(conn, name)["uid"])


def _document(uid: str) -> Dict[str, Any]:
    try:
        store = boot.engine().store
    except JobError as exc:
        raise refusal_error(exc) from exc
    rows = store.needs_rows(uid)
    kinds: Dict[str, Any] = {}
    for kind in needs_policy.KINDS:
        filters, prefer = needs_mod.kind_defaults(kind)
        own = rows.get(kind)
        kinds[kind] = {"needs": own[0] if own else [], "prefer": own[1] if own else [], "stored": own is not None,
                       "default_filters": [n.text for n in filters], "default_prefer": [n.text for n in prefer]}
    return {"kinds": kinds, "vocabulary": list(needs_mod.VOCAB)}


@router.get("/projects/{project_name}/delegate-needs")
async def get_delegate_needs(project_name: str) -> Dict[str, Any]:
    """The project's stored needs per kind with the built-in defaults beside them. Raises 404 (unknown project), 503 jobs_not_ready."""
    uid = await run_in_threadpool(_uid, project_name)
    return await run_in_threadpool(_document, uid)


@router.put("/projects/{project_name}/delegate-needs", dependencies=[Depends(_owner_only)])
async def put_delegate_needs(project_name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Replace the stored document of each kind in the body ({kind: {needs, prefer}}; null removes it). Raises 404, 422 bad_needs, 503."""
    uid = await run_in_threadpool(_uid, project_name)
    try:
        store = boot.engine().store
        await run_in_threadpool(needs_policy.put, store, uid, body)
    except JobError as exc:
        raise refusal_error(exc) from exc
    except ValueError as exc:
        raise api_error(422, "bad_needs", exc) from exc
    return await run_in_threadpool(_document, uid)


from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.argent.status import feature_on
from src.api.auth import require_auth
from src.core.argent import work_items, writeback

router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])
_STATUS = {"not_found": 404, "not_in_review": 409, "empty": 422, "blocked_secret": 422}


class WritebackEdit(BaseModel):
    """Example: {"body": "login | Ann's session api | commits: 1 (fix x) | files: 1 (a.py) | cost this window: $0.12 | fixed x."}"""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(..., max_length=writeback.writeback_template.MAX_BODY * 2)


async def _tenant() -> str:
    if not feature_on():
        raise HTTPException(status_code=409, detail={"code": "feature_off", "message": "turn the argent feature on first"})
    tenant = await run_in_threadpool(work_items.current_tenant)
    if not tenant:
        raise HTTPException(status_code=409, detail={"code": "login_required", "message": "log in to argent first"})
    return tenant


def _fail(exc: writeback.EditError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(exc.code, 409), detail={"code": exc.code, "message": exc.code.replace("_", " ")})


@router.get("/writeback/review")
async def get_review() -> Dict[str, Any]:
    """The comments waiting for approval. Output: {enabled, items: [{id, item_id, item_title, milestone, body, session_name, commits, created_at}]}."""
    if not feature_on():
        return {"enabled": False, "items": []}
    tenant = await run_in_threadpool(work_items.current_tenant)
    return {"enabled": True, "items": await run_in_threadpool(writeback.review_list, tenant) if tenant else []}


@router.post("/writeback/{row_id}/approve")
async def post_approve(row_id: int) -> Dict[str, Any]:
    """Send a waiting comment. Raises: 404 ``not_found``, 409 ``not_in_review``, ``feature_off``, ``login_required``."""
    tenant = await _tenant()
    try:
        return await run_in_threadpool(writeback.approve, tenant, row_id)
    except writeback.EditError as exc:
        raise _fail(exc) from None


@router.post("/writeback/{row_id}/edit")
async def post_edit(row_id: int, body: WritebackEdit) -> Dict[str, Any]:
    """Replace a waiting comment's text. Raises: 404 ``not_found``, 409 ``not_in_review``, 422 ``empty`` or ``blocked_secret``."""
    tenant = await _tenant()
    try:
        return await run_in_threadpool(writeback.edit, tenant, row_id, body.body)
    except writeback.EditError as exc:
        raise _fail(exc) from None


@router.post("/writeback/{row_id}/discard")
async def post_discard(row_id: int) -> Dict[str, Any]:
    """Drop a waiting comment. Raises: 404 ``not_found``, 409 ``not_in_review``."""
    tenant = await _tenant()
    try:
        return await run_in_threadpool(writeback.discard, tenant, row_id)
    except writeback.EditError as exc:
        raise _fail(exc) from None


from __future__ import annotations

from typing import Any, Dict, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.argent.status import feature_on
from src.api.auth import require_auth
from src.core import resource_push
from src.core.argent import work_items
from src.core.argent.client import ArgentError, NotFound, Unauthorized, Unreachable, error_code
from src.core.resource_push import topics

logger = structlog.get_logger()
router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])


class WorkItemCreate(BaseModel):
    """A new work item. Example: {"kind": "feature", "parent_id": "wi_proj1", "title": "login rework"}"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["project", "feature", "story"]
    parent_id: Optional[str] = Field(None, max_length=200)
    title: str = Field(..., min_length=1, max_length=200)


def _refuse(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


@router.get("/work-items")
async def list_work_items(kind: Optional[str] = None, parent_id: Optional[str] = None, state: Optional[str] = None,
                          q: Optional[str] = None) -> Dict[str, Any]:
    """The cached work items. Inputs: kind (project, feature, story), parent_id, state (the item's sprint state: active, future, closed, none), q (title substring).

    Output: {enabled, state (off, pending, ok, login_required, login_expired, unavailable), items, rev}.
    Example: GET /api/v1/argent/work-items?kind=story&q=login
    """
    if not feature_on():
        return {"enabled": False, "state": "off", "items": [], "rev": None}
    work_items.touch()
    tenant = await run_in_threadpool(work_items.current_tenant)
    found = await run_in_threadpool(work_items.list_rows, tenant, kind=kind or "", parent_id=parent_id or "", sprint_state=state or "", q=q or "") \
        if tenant else {"items": [], "rev": None}
    return {"enabled": True, "state": work_items.state(), **found}


@router.post("/work-items")
async def create_work_item(body: WorkItemCreate) -> Dict[str, Any]:
    """Create an item in Argent and cache it. Output: Argent's row plus ``created`` (True for a new item, False when Argent joined an existing one). Raises: 409 ``feature_off``, 409 ``conflict`` (with ``details.candidates``
    from Argent; the owner confirms a join), 403 ``login_required``, 502 ``argent_unreachable``, 503 ``unavailable``, or Argent's own 4xx.
    Example: POST /api/v1/argent/work-items {"kind": "story", "parent_id": "wi_feat1", "title": "fix login"}
    """
    if not feature_on():
        raise _refuse(409, "feature_off", "turn the argent feature on first")
    payload = {"kind": body.kind, "parent_id": body.parent_id, "title": body.title.strip()}
    try:
        client, tenant = await work_items.client_for_call()
        reply = await client.post("/v1/my/work-items", json=payload)
    except Unauthorized as exc:
        raise _refuse(403, "login_expired" if exc.code != "login_required" else "login_required", "log in to argent again") from None
    except NotFound as exc:
        if error_code(exc.body) == "not_found":
            raise _refuse(404, "parent_not_found", "that parent work item is not one you can see") from None
        raise _refuse(503, "unavailable", "argent cannot create work items yet") from None
    except Unreachable:
        raise _refuse(502, "argent_unreachable", "argent did not answer") from None
    except ArgentError as exc:
        err = exc.body.get("error") if isinstance(exc.body.get("error"), dict) else {}
        if exc.status == 409:
            raise _refuse(409, "conflict", str(err.get("message") or "a similar work item exists"), details=err.get("details") or {}) from None
        raise _refuse(exc.status or 502, exc.code or "argent_refused", str(err.get("message") or "argent refused")) from None
    row = reply.body.get("item") if isinstance(reply.body.get("item"), dict) else reply.body
    if await run_in_threadpool(work_items.upsert, tenant, row):
        resource_push.notify(topics.ARGENT_WORK_ITEMS)
    return {**row, "created": reply.status == 201}

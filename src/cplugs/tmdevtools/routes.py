
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from src.cplugs.sdk import CplugContext, cplug_context, cplug_router
from src.cplugs.tmdevtools import commands, service
from src.cplugs.tmdevtools.errors import DevToolsError

router = cplug_router("tmdevtools")
Ctx = Depends(cplug_context("tmdevtools"))


class ScrollBody(BaseModel):
    """``POST /scroll-top``: the project to show first (optional)."""

    model_config = ConfigDict(extra="forbid")
    list: Optional[str] = None


class FoldBody(BaseModel):
    """``POST /fold``: see :func:`service.fold` for the meaning."""

    model_config = ConfigDict(extra="forbid")
    action: str
    items: Optional[list[int]] = None
    group: Optional[Any] = None
    project: Optional[str] = None


def _http(exc: DevToolsError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "detail": str(exc)})


@router.get("/commands")
async def read_commands(after: Optional[int] = Query(None, ge=0), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The commands a browser has not applied. Inputs: after (newest applied seq). Output: {commands, latest}."""
    return {"commands": commands.since(ctx, after), "latest": commands.latest(ctx)}


@router.post("/scroll-top")
async def post_scroll_top(body: ScrollBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Scroll the Task Manager to the top everywhere. Output: {sent, seq, list}."""
    try:
        return await service.scroll_top(ctx, body.list)
    except DevToolsError as exc:
        raise _http(exc) from exc


@router.post("/fold")
async def post_fold(body: FoldBody, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Fold, unfold or close everywhere. Output: {sent, seq, action, items, groups, project}."""
    try:
        return await service.fold(ctx, body.model_dump(exclude_none=True))
    except DevToolsError as exc:
        raise _http(exc) from exc


@router.get("/tasks")
async def get_tasks(view: Optional[str] = None, project: Optional[str] = None, status: Optional[str] = None, section: Optional[str] = None,
                    group: Optional[str] = None, tag: Optional[str] = None, kind: Optional[str] = None) -> Dict[str, Any]:
    """Compact task rows or projects. Output: see the module docstring."""
    args = {"view": view, "project": project, "status": status, "section": section, "group": group, "tag": tag, "kind": kind}
    try:
        return await service.list_tasks({k: v for k, v in args.items() if v is not None})
    except DevToolsError as exc:
        raise _http(exc) from exc

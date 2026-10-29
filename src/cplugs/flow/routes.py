
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.cplugs.flow import service
from src.cplugs.sdk import OWN_POLICY_HEADER, CplugContext, cplug_context, cplug_router
from src.cplugs.sdk.sandboxed_html import view_headers

HTML_FILE_NAME = "flow-run.html"

router = cplug_router("flow")
Ctx = Depends(cplug_context("flow"))


def _refusal(exc: Exception) -> HTTPException:
    if isinstance(exc, service.SeedNotFound):
        return HTTPException(status_code=404, detail={"code": "flow_seed_not_found", "detail": str(exc)})
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail={"code": "flow_invalid", "detail": str(exc)})
    return HTTPException(status_code=503, detail={"code": "flow_unavailable", "detail": str(exc)[:300]})


@router.get("/run", response_model=None)
async def run(seed: str = Query("huddle_item", max_length=20), id: str = Query(..., min_length=1, max_length=200),
              start: Optional[float] = Query(None, ge=0), end: Optional[float] = Query(None, ge=0),
              refresh: bool = Query(False), html: bool = Query(False), ctx: CplugContext = Ctx) -> Any:
    """Build or reuse a run. Output: see the module docstring."""
    try:
        built = await service.get_run(ctx, seed, id, start=start, end=end, refresh=refresh)
    except (service.SeedNotFound, ValueError, service.ActivityUnavailable) as exc:
        raise _refusal(exc) from exc
    if not html:
        return built
    return HTMLResponse(service.as_page(built)["html"], headers={**view_headers(HTML_FILE_NAME), OWN_POLICY_HEADER: "1"})


@router.get("/feed", response_model=None)
async def feed(seed: str = Query("huddle_item", max_length=20), id: str = Query(..., min_length=1, max_length=200),
               start: Optional[float] = Query(None, ge=0), cursor: Optional[float] = Query(None, ge=0),
               ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The chat view's items after a cursor. Output: see the module docstring."""
    try:
        return await service.get_feed(ctx, seed, id, start=start, cursor=cursor)
    except (service.SeedNotFound, ValueError, service.ActivityUnavailable) as exc:
        raise _refusal(exc) from exc

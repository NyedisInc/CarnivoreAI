"""The ``flow`` plugin's one route: reconstruct a multi-agent run (``docs/flow.md``).

Under ``/api/v1/cplugs/flow``, behind ``require_auth`` and the plugin's switch (off: 409 ``cplug_disabled``).

  GET /run?seed=huddle_item|session&id=<item number | session reference>&start=&end=&refresh=&html=
        seed (default huddle_item); id (an item number, or a session uuid, tmux name, conversation id or ``ses_`` id);
        start, end (epoch seconds; default: the item's life plus 30 minutes, or the last 6 hours for a session);
        refresh (rebuild instead of reusing a finished snapshot); html (true: answer the standalone page as
        ``text/html`` instead of JSON).
        200 {version, seed, window, sources, lanes, blocks, edges, marks, events, idle_gaps, stats, warnings,
             snapshot: {built_at, cached}}. A lane is {id, kind: session|subagent|owner, label, parent, order, ...}; a
        block {id, lane, kind: turn|tool|subagent, start, end, label, origin, tools, source}; an edge {id, kind:
        crosstalk|spawn|subagent_launch|subagent_return|huddle_post|owner_reply, from: {lane, t}, to: {lane, t}, label,
        inferred, source, ...}; a mark {id, lane, t, kind: huddle_add|card, label, inferred, source}.
        404 {code: flow_seed_not_found}; 422 {code: flow_invalid}; 503 {code: flow_unavailable}.

  GET /feed?seed=huddle_item|session&id=<ref>&start=&cursor=
        The chat view (``feed.py``): the same run as bubbles and cards in causal order. cursor (the previous answer's
        ``cursor``; absent: everything); start (pin the window start, the first answer's ``window.start``). Takes a
        45 s lease that makes the plugin name ``cplug.flow.feed`` when a session of the run writes (``live.py``).
        200 {seed, window, lanes: [{id, kind, label, parent, depth, color}], items: [{id, kind: bubble|work|crosstalk|
             spawn|launch|return|Task Manager|task, lane, t, u, ...}], cursor, total, full, warnings}. Errors as /run.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from src.cplugs.flow import service
from src.cplugs.sdk import CplugContext, cplug_context, cplug_router

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
    return HTMLResponse(service.as_page(built)["html"]) if html else built


@router.get("/feed", response_model=None)
async def feed(seed: str = Query("huddle_item", max_length=20), id: str = Query(..., min_length=1, max_length=200),
               start: Optional[float] = Query(None, ge=0), cursor: Optional[float] = Query(None, ge=0),
               ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The chat view's items after a cursor. Output: see the module docstring."""
    try:
        return await service.get_feed(ctx, seed, id, start=start, cursor=cursor)
    except (service.SeedNotFound, ValueError, service.ActivityUnavailable) as exc:
        raise _refusal(exc) from exc

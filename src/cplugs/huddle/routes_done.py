
from __future__ import annotations

from typing import Any, Dict

from fastapi import Query
from fastapi.responses import JSONResponse

from src.cplugs.huddle import lane, owner_read, service, slim
from src.cplugs.huddle.routes import Ctx, refusal, router, run_store
from src.cplugs.huddle.rules import TaskManagerError, check_list_key
from src.cplugs.huddle.store_reads import DONE_MAX, DONE_PAGE
from src.cplugs.sdk import CplugContext


@router.get("/lists/{key}/done")
async def get_list_done(key: str, limit: int = Query(DONE_PAGE, ge=1, le=DONE_MAX), offset: int = Query(0, ge=0),
                        threads: bool = Query(False), include_swarm: bool = Query(False), ctx: CplugContext = Ctx) -> JSONResponse:
    """One page of a list's completed items with their threads (see the module docstring). Output: the page, rendered straight to JSON."""
    try:
        check_list_key(key)
    except TaskManagerError as exc:
        raise refusal(exc) from exc
    page: Dict[str, Any] = await run_store(lambda: service.store(ctx).done_page(
        key, hide_swarm=lane.hides_swarm(key, include_swarm), limit=limit, offset=offset))
    items = page["items"] if threads else [slim.slim_item(i) for i in page["items"]]
    await owner_read.annotate_tagged(ctx, items)
    return JSONResponse({**page, "items": items})

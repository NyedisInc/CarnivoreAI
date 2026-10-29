
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Query
from pydantic import BaseModel, ConfigDict

from src.cplugs.huddle import old_routes, send_queue
from src.cplugs.huddle.routes import Ctx, router
from src.cplugs.sdk import CplugContext


class FlushRequest(BaseModel):
    """The lists to send now; absent means every queued list."""

    model_config = ConfigDict(extra="forbid")
    lists: Optional[List[str]] = None


@router.get("/send-queue")
@router.get("/tell-queue", **old_routes.retired("GET", "/tell-queue"))
async def get_send_queue(lists: Optional[str] = Query(None), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The pending queue of plain-change tells, its window and when it sends.

    Inputs: lists (comma separated list keys; absent: all). Output: ``SendQueue.snapshot`` (count 0 and null times with nothing queued).
    """
    only = [k for k in lists.split(",") if k] if lists is not None else None
    return send_queue.state(ctx, only)


@router.post("/send-queue/flush")
@router.post("/tell-queue/flush", **old_routes.retired("POST", "/tell-queue/flush"))
async def flush_send_queue(body: FlushRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Send the queued tells now, each list into its own session, and empty the queue (the key's click).

    Description: the same per-list outcomes as ``POST /tell`` (``sent``, ``no_session`` with candidates, ``refused``, ``held``), plus
      ``nothing`` for a list another path had already told. With nothing queued the answer is an empty ``results``.
    Output: {results: [...], queue: the snapshot after}.
    """
    results = await send_queue.flush_now(ctx, body.lists)
    return {"results": results, "queue": send_queue.state(ctx)}

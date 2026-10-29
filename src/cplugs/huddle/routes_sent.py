
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import Query

from src.cplugs.huddle import held, sent, service, send_queue
from src.cplugs.huddle.routes import Ctx, router, run_store
from src.cplugs.sdk import CplugContext

DEFAULT_LIMIT = 40


@router.get("/sent")
async def get_sent(limit: int = Query(DEFAULT_LIMIT, ge=1, le=sent.MAX_LIMIT), ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The owner's recent sends with their tell states, newest first. Output: {now, sends}."""
    store = service.store(ctx)
    names = await run_store(lambda: service.project_names(ctx))
    queue = send_queue.state(ctx).get("lists", {})
    holds = {h["list"]: h for h in held.snapshot()}
    labels = {i.session.id: i.label or i.tmux_session or i.session.id for i in await ctx.sessions.list()}
    sends = await run_store(lambda: sent.gather(store, limit=limit, names=names, queue=queue, holds=holds, labels=labels))
    return {"now": time.time(), "sends": sends}

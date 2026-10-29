
from __future__ import annotations

from typing import Any, Dict

from src.cplugs.huddle import actor_log, service
from src.cplugs.huddle.routes import Ctx, router, run_store
from src.cplugs.sdk import CplugContext


@router.get("/items/{item_id}/actors")
async def item_actors(item_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The write log and source link of one item. Output: {item_id, source_item_id, actors}. 404 for an unknown item."""
    store = service.store(ctx)

    def read() -> Dict[str, Any]:
        store.item(item_id)
        return actor_log.actors_of(store, item_id)

    return await run_store(read)

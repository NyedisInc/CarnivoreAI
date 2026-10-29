
from __future__ import annotations

from contextlib import closing
from typing import Any, Dict

from src.cplugs.huddle import lineage, service
from src.cplugs.huddle.routes import Ctx, router, run_store
from src.cplugs.huddle.rules import TaskManagerNotFound
from src.cplugs.sdk import CplugContext


@router.get("/items/{item_id}/lineage")
async def item_lineage(item_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """The state moves of one item, deleted or not. Output: {item_id, deleted, lineage}. 404 ``task_manager_not_found`` for an id that never existed."""
    store = service.store(ctx)

    def read() -> Dict[str, Any]:
        with closing(store._read_connection()) as conn:
            row = conn.execute("SELECT deleted FROM work_items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise TaskManagerNotFound(f"no huddle item {item_id}")
            return {"item_id": item_id, "deleted": bool(row[0]), "lineage": lineage.for_item(conn, item_id)}

    return await run_store(read)

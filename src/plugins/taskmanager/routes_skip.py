
from __future__ import annotations

from typing import Any, Dict

from src.plugins.taskmanager import service
from src.plugins.taskmanager.routes_common import Ctx, decide_card, refusal, router, run_store
from src.plugins.taskmanager.rules import TaskManagerInvalid
from src.plugins.sdk import CplugContext

QUESTION_REF, SKIP = "question:", "skip"


@router.post("/items/{item_id}/skip")
async def post_skip(item_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Skip one Swarm question card, as the owner. Output: the item. Raises: 400 (not a question card), 404, 409 (the Swarm refused)."""
    store = service.store(ctx)
    item = await run_store(lambda: store.item(item_id))
    if not str(item.get("swarm_ref") or "").startswith(QUESTION_REF):
        raise refusal(TaskManagerInvalid("only a Swarm question card can be skipped"))
    await decide_card(ctx, item, SKIP)
    return await run_store(lambda: store.item(item_id))

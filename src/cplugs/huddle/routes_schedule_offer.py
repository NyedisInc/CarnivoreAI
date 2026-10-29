
from __future__ import annotations

from typing import Any, Dict

from src.cplugs.huddle import reply, schedule_offer, service
from src.cplugs.huddle.routes import Ctx, mapped_errors, router, run_store
from src.cplugs.sdk import CplugContext


@router.post("/items/{item_id}/messages/{message_id}/schedule")
async def accept_schedule_offer(item_id: int, message_id: int, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Accept the schedule an agent offered on a message: record it, then cue the agent on the thread. Output: {offer, message, reply}."""
    accepted = await run_store(lambda: service.store(ctx).accept_schedule(item_id, message_id))
    with mapped_errors():
        posted = await reply.post_reply(ctx, item_id, schedule_offer.instruction(accepted["offer"], message_id), ack_through=0)
    return {**accepted, "reply": posted["message"]}

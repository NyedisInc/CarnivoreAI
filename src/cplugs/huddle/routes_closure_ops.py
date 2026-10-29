
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.cplugs.huddle import closure_undo, held, sent, send_queue, service
from src.cplugs.huddle.routes import Ctx, router, run_store
from src.cplugs.sdk import CplugContext


class UndoRequest(BaseModel):
    """Undo body: the revision the client read (a double click or a second window fails the check)."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class CancelRequest(UndoRequest):

    note: Optional[str] = Field(default=None, max_length=closure_undo.MAX_NOTE)


async def delivery_of(ctx: CplugContext, item: Dict[str, Any], message: Dict[str, Any]) -> Dict[str, Any]:
    await send_queue.queue_owner_write(ctx, item)
    holds = {h["list"]: h for h in held.snapshot()}
    tell = await run_store(lambda: sent.tell_of_message(service.store(ctx), message["id"], queue=send_queue.state(ctx).get("lists", {}), holds=holds)) or {}
    return {"delivery_id": f"m:{message['id']}", "message_id": message["id"], "status": tell.get("state", sent.WAITING), "due_at": tell.get("due_at"), "text": message["text"]}


@router.post("/items/{item_id}/undo-completion")
async def post_undo_completion(item_id: int, body: UndoRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Withdraw the task's newest closure and tell the agent. Output: {item, retraction}. Raises: 409 stale or not allowed, 404."""
    done = await run_store(lambda: closure_undo.undo_completion(service.store(ctx), item_id, body.expected_revision))
    return {"item": done["item"], "retraction": await delivery_of(ctx, done["item"], done["message"])}


@router.post("/items/{item_id}/cancel")
async def post_cancel_task(item_id: int, body: CancelRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Cancel the task (closed with outcome cancelled, schedule removed) and tell the agent. Output: {item, notice}. Raises: 409 stale or not allowed, 404."""
    done = await run_store(lambda: closure_undo.cancel_task(service.store(ctx), item_id, body.expected_revision, body.note))
    return {"item": done["item"], "notice": await delivery_of(ctx, done["item"], done["message"])}

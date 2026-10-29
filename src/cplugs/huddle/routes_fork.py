
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, StrictInt

from src.cplugs.huddle import service
from src.cplugs.huddle.groups import UNSET
from src.cplugs.huddle.routes import Ctx, known_list, router, run_store
from src.cplugs.huddle.rules import JOE
from src.cplugs.sdk import CplugContext


class ForkRequest(BaseModel):
    """A fork: everything optional. ``group`` sent (null included) files it in that group of its list; absent keeps the parent's."""

    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    text: Optional[str] = None
    list: Optional[str] = None
    group: Optional[StrictInt] = None
    fork_state: Optional[str] = None
    parent_state: Optional[str] = None
    parent_waits: bool = False
    review_description: Optional[str] = None
    review_summary: Optional[str] = None
    review_link: Optional[str] = None
    review_where: Optional[str] = None
    review_action: Optional[str] = None


@router.post("/items/{item_id}/fork")
async def fork_item(item_id: int, body: ForkRequest, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    """Fork one item, as joe: the copy and either or both states in one transaction. Output: {fork, parent}."""
    key = (await known_list(ctx, body.list))[0] if body.list is not None else None
    group = body.group if "group" in body.model_fields_set else UNSET
    return await run_store(lambda: service.store(ctx).fork(
        item_id, actor=JOE, title=body.title, text=body.text, list_key=key, group=group, fork_state=body.fork_state,
        parent_state=body.parent_state, review_fields=body.model_dump(include={"review_description", "review_summary", "review_link", "review_where", "review_action"}, exclude_none=True),
        parent_waits=body.parent_waits))

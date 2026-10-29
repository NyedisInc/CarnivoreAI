
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from src.cplugs.reviewboard import document, ports, revisions, state, store, wire
from src.cplugs.reviewboard.errors import TaskNotFound
from src.cplugs.reviewboard.requests import RelinkBody
from src.cplugs.reviewboard.rounds import JOE
from src.cplugs.reviewboard.schema import Sidecar
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.computer import local_computer


async def relink(ctx: CplugContext, slug: str, body: RelinkBody) -> Dict[str, Any]:
    info = await ports.get().item_info(body.item_id)
    if info is None:
        raise TaskNotFound(f"there is no huddle item {body.item_id} on this computer")
    now, here = revisions.utcnow(), local_computer()

    def build(current: Optional[Sidecar]):
        assert current is not None
        if current.task is not None and current.task.item_id == body.item_id and current.task.computer in (None, here):
            raise store.NoChange()
        doc = current.model_dump(mode="json", by_alias=True)
        old = doc["task"] or {}
        change = {"item_id": body.item_id, "computer": here, "at": revisions.stamp(now), "by": JOE}
        if old.get("item_id"):
            change["from"] = old["item_id"]
        doc["task"] = {"item_id": body.item_id, "list": info.get("list"), "computer": here, "github_issue": info.get("github_issue"),
                       "title_at_link": (info.get("title") or f"item {body.item_id}")[:200], "linked_at": revisions.stamp(now),
                       "history": [*old.get("history", []), change]}
        return doc, {}

    text, tag = await asyncio.to_thread(store.append, wire.board_root(ctx), ctx.storage.path, slug, body.base_etag, build)
    sidecar = document.parse_sidecar(json.loads(text))
    ctx.notify(TOPIC)
    return {"task": sidecar.task.model_dump(mode="json", by_alias=True) if sidecar.task else None, "etag": tag, "state": state.board_state(sidecar)}

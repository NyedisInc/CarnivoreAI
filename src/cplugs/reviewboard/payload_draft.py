
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from src.cplugs.reviewboard import document, payloads, revisions, store, wire
from src.cplugs.reviewboard.requests import PayloadDraftBody
from src.cplugs.reviewboard.schema import Sidecar
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import CplugContext


async def save_draft(ctx: CplugContext, slug: str, body: PayloadDraftBody) -> Dict[str, Any]:
    changed: Dict[str, bool] = {}

    def build(current: Optional[Sidecar]):
        assert current is not None
        doc = current.model_dump(mode="json", by_alias=True)
        changed["now"] = payloads.set_draft(doc, body.revision, body.payload, revisions.stamp(revisions.utcnow()))
        if not changed["now"]:
            raise store.NoChange()
        return doc, {}

    text, tag = await asyncio.to_thread(store.append, wire.board_root(ctx), ctx.storage.path, slug, None, build)
    if changed.get("now"):
        ctx.notify(TOPIC)
    row = next(r for r in document.parse_sidecar(json.loads(text)).revisions if r.id == body.revision)
    assert row.draft is not None
    return {"revision": body.revision, "draft": {"at": row.draft.at}, "etag": tag, "changed": bool(changed.get("now"))}

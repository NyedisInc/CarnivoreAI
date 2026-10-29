
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import structlog

from src.cplugs.reviewboard import document, payloads, revisions, store, wire
from src.cplugs.reviewboard.requests import SaveBody
from src.cplugs.reviewboard.schema import Sidecar
from src.cplugs.reviewboard.topics import TOPIC
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()


async def save_payload(ctx: CplugContext, slug: str, body: SaveBody) -> Dict[str, Any]:
    made: Dict[str, int] = {}

    def build(current: Optional[Sidecar]):
        assert current is not None
        doc = current.model_dump(mode="json", by_alias=True)
        made["n"] = payloads.add_save(doc, body.revision, body.payload, body.note, revisions.stamp(revisions.utcnow()))
        return doc, {}

    text, tag = await asyncio.to_thread(store.append, wire.board_root(ctx), ctx.storage.path, slug, body.base_etag, build)
    ctx.notify(TOPIC)
    row = next(r for r in document.parse_sidecar(json.loads(text)).revisions if r.id == body.revision)
    save = next(s for s in row.saves or [] if s.n == made["n"])
    logger.info("reviewboard_payload_saved", slug=slug, revision=body.revision, save=save.n)
    return {"revision": body.revision, "save": save.model_dump(mode="json"), "etag": tag}

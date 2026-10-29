
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import structlog
from pydantic import ValidationError

from src.cplugs.reviewboard import pages, publish, wire
from src.cplugs.reviewboard.errors import BoardError
from src.cplugs.reviewboard.requests import CreateBody, ReviseBody
from src.cplugs.sdk import AgentCaller, CplugContext, ports

logger = structlog.get_logger()

NAME = "reviewboard.artifacts"


class ArtifactPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    async def publish(self, caller: Optional[AgentCaller], item_id: int, *, title: str, description: str, html: str,
                      cross_project: bool = False) -> Optional[Dict[str, Any]]:
        summary = (description or title).strip()
        try:
            root = wire.explicit_root(self._ctx)
            slug = await asyncio.to_thread(pages.existing_board, root, item_id, title)
            if slug is not None:
                body = ReviseBody.model_validate(pages.revise_args(summary, html))
                return await publish.add_revision(self._ctx, slug, body, caller, cross_project)
            taken = await asyncio.to_thread(pages.taken_today, root)
            body = CreateBody.model_validate(pages.create_args(item_id, title, summary, html, taken))
            return await publish.create_board(self._ctx, body, caller, cross_project)
        except BoardError as exc:
            logger.info("reviewboard_artifact_declined", item=item_id, code=exc.code, reason=str(exc)[:200])
            return None
        except ValidationError as exc:
            logger.info("reviewboard_artifact_declined", item=item_id, code="invalid", reason=str(exc)[:200])
            return None


def register(ctx: CplugContext) -> None:
    ports.register(NAME, ArtifactPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)


from __future__ import annotations

import asyncio

import pydantic
import structlog

from src.cplugs.reviewboard import relink
from src.cplugs.reviewboard.errors import BoardError
from src.cplugs.reviewboard.requests import RelinkBody
from src.cplugs.sdk import CplugContext, ports

logger = structlog.get_logger()

NAME = "reviewboard.relink"


class RelinkPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    def relink(self, slug: str, item_id: int) -> bool:
        try:
            body = RelinkBody(item_id=item_id)
            asyncio.run(relink.relink(self._ctx, slug, body))
        except (BoardError, pydantic.ValidationError, OSError) as exc:
            logger.warning("reviewboard_import_relink_failed", slug=slug, item_id=item_id, error_type=type(exc).__name__, error=str(exc)[:160])
            return False
        return True


def register(ctx: CplugContext) -> None:
    ports.register(NAME, RelinkPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)

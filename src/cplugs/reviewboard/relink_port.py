
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
        """
        Blocking: it runs the writer on its own event loop, so call it from a worker thread (a crate import is one), never from the loop.
        Inputs: slug; item_id. Output: True when the board is linked to ``item_id`` now; False when it could not be (no board, no such task, the
        Task Manager off, a board read only here, a failed write), logged with the reason. Example: port.relink("20261019-crate-carry-test", 1) -> True
        """
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

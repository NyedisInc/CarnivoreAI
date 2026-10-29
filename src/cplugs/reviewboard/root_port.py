
from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog

from src.cplugs.reviewboard import wire
from src.cplugs.reviewboard.errors import NoRoot
from src.cplugs.sdk import CplugContext, ports

logger = structlog.get_logger()

NAME = "reviewboard.root"


class RootPort:

    def __init__(self, ctx: CplugContext) -> None:
        self._ctx = ctx

    def root(self) -> Optional[Path]:
        try:
            return wire.explicit_root(self._ctx)
        except NoRoot as exc:
            logger.debug("reviewboard_root_unusable", reason=exc.reason)
            return None


def register(ctx: CplugContext) -> None:
    ports.register(NAME, RootPort(ctx))


def unregister() -> None:
    ports.unregister(NAME)

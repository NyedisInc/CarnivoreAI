
from __future__ import annotations

from typing import Optional

import structlog

from src.cplugs.sdk.swarm import ThreadPort

logger = structlog.get_logger()

_port: Optional[ThreadPort] = None


def register(port: Optional[ThreadPort]) -> None:
    global _port
    _port = port
    logger.info("swarm_thread_port", registered=port is not None)


def get() -> Optional[ThreadPort]:
    return _port

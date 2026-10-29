
from __future__ import annotations

from typing import Optional

import structlog

from src.cplugs.sdk.cards import CardPort

logger = structlog.get_logger()

_port: Optional[CardPort] = None


class CardsOff(RuntimeError):
    pass


def register(port: Optional[CardPort]) -> None:
    global _port
    _port = port
    logger.info("swarm_card_port", registered=port is not None)


def get() -> CardPort:
    if _port is None:
        raise CardsOff("the huddle plugin is off, so there are no cards")
    return _port

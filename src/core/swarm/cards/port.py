
from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import Optional, Set

import structlog

from src.plugins.sdk.cards import CardPort

logger = structlog.get_logger()

_port: Optional[CardPort] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_pending: Set[Future] = set()


class CardsOff(RuntimeError):
    pass


def register(port: Optional[CardPort], loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    global _port, _loop
    _port, _loop = port, loop if port is not None else None
    logger.info("swarm_card_port", registered=port is not None)


def card_moved(card_id: int, before: str, after: str, reason: str = "") -> None:
    loop = _loop
    if loop is None or loop.is_closed():
        return
    try:
        future = asyncio.run_coroutine_threadsafe(_mirror(card_id, before, after, reason), loop)
    except RuntimeError:
        return
    _pending.add(future)
    future.add_done_callback(_pending.discard)


async def _mirror(card_id: int, before: str, after: str, reason: str = "") -> None:
    from src.core.argent import card_mirror, writeback  # noqa: PLC0415

    if _port is None or not writeback.is_running():
        return
    try:
        card = await _port.card(card_id)
        if card and card.get("column") == after:
            await card_mirror.on_card_moved(before, card, reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("swarm_card_mirror_failed", error_type=type(exc).__name__)


def get() -> CardPort:
    if _port is None:
        raise CardsOff("the huddle plugin is off, so there are no cards")
    return _port


from __future__ import annotations

import asyncio
import socket
from typing import Optional

import structlog
import uvicorn

from src.core.mcp import channel as channel_events

logger = structlog.get_logger()

_shutting_down = False


def is_shutting_down() -> bool:
    return _shutting_down


def begin() -> None:
    global _shutting_down
    _shutting_down = True
    ended = channel_events.REGISTRY.end_all()
    if ended:
        logger.info("streams_ended_for_shutdown", streams=ended)


def reset() -> None:
    global _shutting_down
    _shutting_down = False


class GracefulServer(uvicorn.Server):

    async def shutdown(self, sockets: Optional[list[socket.socket]] = None) -> None:
        begin()
        await asyncio.sleep(0)
        await super().shutdown(sockets)

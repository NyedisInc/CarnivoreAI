
from __future__ import annotations

import asyncio
from typing import Any, Optional, Tuple

import structlog

logger = structlog.get_logger()


OFFER_ACCEPTED = "accepted"
OFFER_OVERFLOWED = "overflowed"
OFFER_CLOSED = "closed"

REASON_DONE = "done"
REASON_OVERFLOW = "overflow"

OVERFLOW_CLOSE_CODE = 4429


class BoundedStream:

    def __init__(
        self,
        *,
        max_items: int,
        max_bytes: int,
        label: str = "",
    ) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be positive")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._label = label
        self._queue: asyncio.Queue = asyncio.Queue()
        self._queued_bytes = 0
        self._queued_items = 0
        self._closed = False
        self._reason: Optional[str] = None

    @property
    def label(self) -> str:
        return self._label


    def offer(self, item: Any, size: int) -> str:
        if self._closed:
            return OFFER_CLOSED

        cost = size if size > 0 else 0
        would_be_items = self._queued_items + 1
        would_be_bytes = self._queued_bytes + cost
        if would_be_items > self._max_items or would_be_bytes > self._max_bytes:
            return self._on_overflow(item, cost)

        self._admit(item, cost)
        return OFFER_ACCEPTED

    def _admit(self, item: Any, cost: int) -> None:
        self._queued_items += 1
        self._queued_bytes += cost
        self._queue.put_nowait((item, cost))

    def _on_overflow(self, item: Any, cost: int) -> str:
        logger.warning(
            "bounded_stream_overflow",
            label=self._label,
            queued_items=self._queued_items,
            queued_bytes=self._queued_bytes,
            item_bytes=cost,
            max_items=self._max_items,
            max_bytes=self._max_bytes,
        )
        self.close(REASON_OVERFLOW)
        return OFFER_OVERFLOWED


    async def get(self) -> Optional[Any]:
        while True:
            if self._queue.empty() and self._closed:
                return None
            got: Tuple[Any, int] = await self._queue.get()
            item, cost = got
            if item is _SENTINEL:
                continue
            self._queued_items -= 1
            self._queued_bytes -= cost
            return item


    def close(self, reason: str = REASON_DONE) -> None:
        if self._closed:
            return
        self._closed = True
        self._reason = reason
        self._queue.put_nowait((_SENTINEL, 0))

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def overflowed(self) -> bool:
        return self._reason == REASON_OVERFLOW

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    @property
    def queued_items(self) -> int:
        return self._queued_items

    @property
    def queued_bytes(self) -> int:
        return self._queued_bytes

    @property
    def max_items(self) -> int:
        return self._max_items

    @property
    def max_bytes(self) -> int:
        return self._max_bytes


class _Sentinel:
    pass


_SENTINEL = _Sentinel()

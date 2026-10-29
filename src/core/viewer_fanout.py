
from __future__ import annotations

import asyncio
import json
from typing import Any, NamedTuple, Optional

import structlog

from src.core.bounded_stream import (
    OFFER_ACCEPTED,
    REASON_DONE,
    REASON_OVERFLOW,
    OVERFLOW_CLOSE_CODE,
    BoundedStream,
)
from src.models.websocket import WSTerminalResyncMessage

logger = structlog.get_logger()

MAX_VIEWER_QUEUE_CHUNKS = 256
MAX_VIEWER_QUEUE_BYTES = 4 * 1024 * 1024

VIEWER_OVERFLOW_CLOSE_CODE = OVERFLOW_CLOSE_CODE

FRAME_PTY = "pty"
FRAME_TEXT = "text"
FRAME_PAINT = "paint"
FRAME_RESYNC = "resync"

MIN_RESYNC_INTERVAL_SECONDS = 0.1

_RESYNC_LOG_EVERY = 50

_STALE_KINDS = frozenset({FRAME_PTY, FRAME_PAINT, FRAME_RESYNC})


class ViewerFrame(NamedTuple):

    kind: str
    payload: str


class ResyncViewerStream(BoundedStream):

    def __init__(self, *, min_resync_interval: float = MIN_RESYNC_INTERVAL_SECONDS,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._min_interval = min_resync_interval
        self._last_resync: Optional[float] = None
        self._timer: Optional[asyncio.TimerHandle] = None
        self._owed = (0, 0)
        self._queued_marker = (0, 0)
        self.paused = False
        self.held_chunks = 0
        self.resyncs = 0
        self.dropped_chunks = 0
        self.dropped_bytes = 0

    def _drop_stale(self) -> None:
        kept, chunks, size, real_chunks, real_size = [], 0, 0, 0, 0
        carried = self._queued_marker
        while not self._queue.empty():
            entry = self._queue.get_nowait()
            frame, cost = entry
            if isinstance(frame, ViewerFrame) and frame.kind in _STALE_KINDS:
                if frame.kind == FRAME_RESYNC:
                    chunks, size = chunks + carried[0], size + carried[1]
                else:
                    chunks, size = chunks + 1, size + cost
                    real_chunks, real_size = real_chunks + 1, real_size + cost
            else:
                kept.append(entry)
        for entry in kept:
            self._queue.put_nowait(entry)
        self._queued_items = len(kept)
        self._queued_bytes = sum(cost for _, cost in kept)
        self._queued_marker = (0, 0)
        self._owed = (self._owed[0] + chunks, self._owed[1] + size)
        self.dropped_chunks += real_chunks
        self.dropped_bytes += real_size

    def _queue_marker(self, now: float) -> bool:
        chunks, size = self._owed
        payload = json.dumps(WSTerminalResyncMessage(
            dropped_chunks=chunks, dropped_bytes=size).model_dump(mode="json"))
        if (self._queued_items + 1 > self._max_items
                or self._queued_bytes + len(payload) > self._max_bytes):
            return False
        self._admit(ViewerFrame(FRAME_RESYNC, payload), len(payload))
        self._queued_marker, self._owed = (chunks, size), (0, 0)
        self.resyncs += 1
        self._last_resync = now
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self.resyncs == 1 or self.resyncs % _RESYNC_LOG_EVERY == 0:
            logger.info("viewer_resync", label=self._label, resyncs=self.resyncs,
                        dropped_chunks=chunks, dropped_bytes=size)
        return True

    def _flush_deferred(self) -> None:
        self._timer = None
        if self._closed:
            return
        self._drop_stale()
        if not self._queue_marker(asyncio.get_running_loop().time()):
            self.close(REASON_OVERFLOW)

    def resync_now(self) -> None:
        self._drop_stale()
        self._owed = (self._owed[0] + 1, self._owed[1])
        if not self._closed and not self._queue_marker(asyncio.get_running_loop().time()):
            self.close(REASON_OVERFLOW)

    def _owe(self, item: Any, cost: int) -> bool:
        if self._timer is None or not isinstance(item, ViewerFrame) or item.kind not in (FRAME_PTY, FRAME_PAINT):
            return False
        self._owed = (self._owed[0] + 1, self._owed[1] + cost)
        self.dropped_chunks += 1
        self.dropped_bytes += cost
        return True

    def offer(self, item: Any, size: int) -> str:
        if not self._closed and self._owe(item, max(size, 0)):
            return OFFER_ACCEPTED
        return super().offer(item, size)

    def _on_overflow(self, item: Any, cost: int) -> str:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return super()._on_overflow(item, cost)
        self._drop_stale()
        now = loop.time()
        if self._last_resync is None or now - self._last_resync >= self._min_interval:
            if not self._queue_marker(now):
                return super()._on_overflow(item, cost)
        elif self._timer is None:
            self._timer = loop.call_later(
                self._last_resync + self._min_interval - now, self._flush_deferred)
        if self._owe(item, cost):
            return OFFER_ACCEPTED
        if (self._queued_items + 1 > self._max_items
                or self._queued_bytes + cost > self._max_bytes):
            return super()._on_overflow(item, cost)
        self._admit(item, cost)
        return OFFER_ACCEPTED

    def close(self, reason: str = REASON_DONE) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        super().close(reason)


def new_viewer_stream(
    label: str, *, resync: bool = False,
    min_resync_interval: float = MIN_RESYNC_INTERVAL_SECONDS,
) -> BoundedStream:
    kwargs = dict(max_items=MAX_VIEWER_QUEUE_CHUNKS, max_bytes=MAX_VIEWER_QUEUE_BYTES,
                  label=f"viewer {label}")
    if resync:
        return ResyncViewerStream(min_resync_interval=min_resync_interval, **kwargs)
    return BoundedStream(**kwargs)


def offer_pty(stream: BoundedStream, encoded: str) -> str:
    if getattr(stream, "paused", False):
        stream.held_chunks = getattr(stream, "held_chunks", 0) + 1
        return OFFER_ACCEPTED
    return stream.offer(ViewerFrame(FRAME_PTY, encoded), len(encoded))


def offer_text(stream: BoundedStream, text: str) -> str:
    return stream.offer(ViewerFrame(FRAME_TEXT, text), len(text))


def offer_paint(stream: BoundedStream, encoded: str) -> str:
    return stream.offer(ViewerFrame(FRAME_PAINT, encoded), len(encoded))


def is_viewer_stream(candidate: Any) -> bool:
    return (
        hasattr(candidate, "offer")
        and hasattr(candidate, "close")
        and hasattr(candidate, "overflowed")
    )


def close_viewer_stream(candidate: Any) -> None:
    if is_viewer_stream(candidate):
        candidate.close()

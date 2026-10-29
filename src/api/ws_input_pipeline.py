
import asyncio
from collections import deque
from typing import Awaitable, Callable

import structlog

from src.core.tmux_backend import PASTE_THRESHOLD_BYTES

logger = structlog.get_logger()

MAX_PENDING_BYTES: int = 64 * 1024

SendBatch = Callable[[str], Awaitable[None]]
ReportFailure = Callable[[Exception, int], None]


class InputPipeline:

    def __init__(
        self,
        send: SendBatch,
        on_failure: ReportFailure,
        *,
        max_batch_bytes: int = PASTE_THRESHOLD_BYTES,
    ) -> None:
        self._send = send
        self._on_failure = on_failure
        self._max_batch_bytes = max_batch_bytes
        self._frames: "deque[tuple[str, int]]" = deque()
        self._pending_bytes = 0
        self._wake = asyncio.Event()
        self._room = asyncio.Event()
        self._room.set()
        self._closing = False
        self._worker: "asyncio.Task[None] | None" = None

    async def submit(self, text: str) -> None:
        if not text:
            return
        if self._worker is None:
            self._worker = asyncio.get_running_loop().create_task(self._run())
        await self._room.wait()
        size = len(text.encode("utf-8"))
        self._frames.append((text, size))
        self._pending_bytes += size
        if self._pending_bytes > MAX_PENDING_BYTES:
            self._room.clear()
        self._wake.set()

    def _take_batch(self) -> "tuple[str, int]":
        text, size = self._frames.popleft()
        parts = [text]
        while self._frames and size + self._frames[0][1] <= self._max_batch_bytes:
            nxt, nxt_size = self._frames.popleft()
            parts.append(nxt)
            size += nxt_size
        return "".join(parts), size

    async def _run(self) -> None:
        while True:
            if not self._frames:
                if self._closing:
                    return
                self._wake.clear()
                await self._wake.wait()
                continue
            batch, size = self._take_batch()
            self._pending_bytes -= size
            if self._pending_bytes <= MAX_PENDING_BYTES:
                self._room.set()
            try:
                await self._send(batch)
            except Exception as exc:  # noqa: BLE001
                self._on_failure(exc, size)

    async def close(self) -> None:
        self._closing = True
        self._wake.set()
        worker = self._worker
        if worker is None:
            return
        try:
            await worker
        except asyncio.CancelledError:
            worker.cancel()
            raise

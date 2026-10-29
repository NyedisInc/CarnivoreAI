
from __future__ import annotations

import asyncio
import select
from typing import Optional

import structlog

logger = structlog.get_logger()

KQUEUE_AVAILABLE: bool = hasattr(select, "kqueue")

WATCHED_BACKSTOP_SECONDS: float = 1.0


class PipeWaiter:

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._kq: Optional["select.kqueue"] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._watching = False
        self._waiter: Optional[asyncio.Future] = None
        self._pending_data = False
        if KQUEUE_AVAILABLE:
            self._try_watch()

    @property
    def watching(self) -> bool:
        return self._watching

    def backstop(self, poll_seconds: float) -> float:
        return WATCHED_BACKSTOP_SECONDS if self._watching else poll_seconds

    def _try_watch(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        kq = None
        try:
            kq = select.kqueue()
            kq.control(
                [
                    select.kevent(
                        self._fd,
                        filter=select.KQ_FILTER_VNODE,
                        flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                        fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND,
                    )
                ],
                0,
                0,
            )
            loop.add_reader(kq.fileno(), self._on_kqueue_readable)
        except (OSError, ValueError, NotImplementedError) as exc:
            logger.debug(
                "pipe_waiter_watch_unavailable",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            try:
                if kq is not None:
                    kq.close()
            except OSError:
                pass
            return
        self._kq = kq
        self._loop = loop
        self._watching = True

    def _on_kqueue_readable(self) -> None:
        kq = self._kq
        if kq is None:
            return
        try:
            kq.control(None, 8, 0)
        except OSError:
            self._detach()
        self._pending_data = True
        waiter = self._waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(True)

    async def wait(self, timeout: float) -> bool:
        if not self._watching or self._loop is None:
            await asyncio.sleep(timeout)
            return False
        if self._pending_data:
            self._pending_data = False
            return True
        loop = self._loop
        waiter = loop.create_future()
        self._waiter = waiter
        timer = loop.call_later(timeout, self._resolve_timeout, waiter)
        try:
            woke = await waiter
        except asyncio.CancelledError:
            raise
        finally:
            timer.cancel()
            self._waiter = None
        self._pending_data = False
        return bool(woke)

    @staticmethod
    def _resolve_timeout(waiter: "asyncio.Future") -> None:
        if not waiter.done():
            waiter.set_result(False)

    def _detach(self) -> None:
        kq, loop = self._kq, self._loop
        self._watching = False
        if loop is not None and kq is not None:
            try:
                loop.remove_reader(kq.fileno())
            except (OSError, ValueError, RuntimeError):
                pass
        if kq is not None:
            try:
                kq.close()
            except OSError:
                pass
        self._kq = None
        self._loop = None

    def close(self) -> None:
        self._detach()

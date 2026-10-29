"""Wake the pipe reader when tmux appends, instead of asking every 20ms.

WHY THIS FILE EXISTS. ``TmuxBackend._tail_loop`` reads the pipe-pane file
with a non-blocking fd and, whenever the read comes back empty, sleeps a
fixed 20ms before trying again. That sleep is a FLOOR ON KEYSTROKE
LATENCY: the echo of a keypress lands in the file at a uniformly random
point inside the window, so the reader sees it about 10ms late on
average and 20ms late at worst, every keystroke, for as long as the app
exists. Measured end to end on a throwaway socket - ``backend.write``
through tmux, the PTY, pipe-pane and back out of ``on_output`` - the
round trip was **p50 25.3ms**, of which that wait is the largest single
component after the ``send-keys`` subprocess.

WHY kqueue AND NOT A SHORTER POLL OR A WATCHER LIBRARY. The producer is
``sh -c "cat >> <file>"``, a separate process appending to a REGULAR
FILE, so the honest options were a shorter poll, repeated ``os.stat``, or
a kernel file-change notification. Both polling options trade CPU for
latency on every idle pane, and this app routinely holds a dozen. kqueue
is in the standard library on macOS (``select.kqueue``), needs no
dependency, and was MEASURED against the exact producer before any of
this was written: ``EVFILT_VNODE`` with ``NOTE_WRITE | NOTE_EXTEND``
fired for all 12 of 12 appends by a real ``cat >>``, **p50 0.024ms**.

THE TIMEOUT IS NOT DECORATION, IT IS THE WHOLE SAFETY ARGUMENT. An
event-driven reader that misses one event does not read late, it stops
reading - the terminal goes silent until something else happens to
append. So every wait is bounded by the SAME interval the old poll used,
and a timeout simply falls through to the read that would have happened
anyway. A platform with no kqueue (Linux, where CI runs) gets the plain
sleep and behaves precisely as before.

THE WATCHED BACKSTOP IS LONGER THAN THE POLL (#1180). The first version
kept the 20 ms poll as the backstop of a watched wait too, so every idle
pane still woke the event loop 50 times a second; on a test slot with
eight panes that was most of the loop's idle CPU. While the watch is
active the backstop is :data:`WATCHED_BACKSTOP_SECONDS`: an append still
ends the wait at once, and only a notification the kernel never delivered
could be late, by at most that long.
"""

from __future__ import annotations

import asyncio
import logging
import select
from typing import Optional

logger = logging.getLogger(__name__)

KQUEUE_AVAILABLE: bool = hasattr(select, "kqueue")

WATCHED_BACKSTOP_SECONDS: float = 1.0


class PipeWaiter:
    """Wait until a file is appended to, or until a timeout expires.

    Description: one instance per open pipe fd, owned by the tail loop
        that opened it. ``wait()`` returns as soon as the kernel reports
        an append, and otherwise after ``timeout`` seconds - so a caller
        that loses an event is late by the timeout rather than stuck
        forever.

        Falls back to ``asyncio.sleep(timeout)`` whenever a watch cannot
        be set up, for any reason: no kqueue on this platform, an event
        loop that will not watch the descriptor, or a kernel refusal on
        this particular fd. Every one of those degrades to EXACTLY the
        behaviour that existed before this class, which is why the
        fallback is silent about correctness and only logs at debug.
    Inputs: see :meth:`__init__`.
    Output: an awaitable ``wait`` and an idempotent ``close``.
    Example:
        waiter = PipeWaiter(fd)
        await waiter.wait(0.02)
        waiter.close()
    """

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
            logger.debug("pipe_waiter_watch_unavailable", exc_info=False)
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

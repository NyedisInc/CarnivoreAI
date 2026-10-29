
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

DEFAULT_DUTY: float = 0.35
DEFAULT_SLICE_SECONDS: float = 20.0


class Throttle:

    def __init__(self, duty: float = DEFAULT_DUTY, slice_seconds: float = DEFAULT_SLICE_SECONDS,
                 sleep: Optional[Callable[[float], None]] = None, clock: Callable[[], float] = time.monotonic) -> None:
        if not 0 < duty <= 1:
            raise ValueError("duty must be in (0, 1]")
        self._ratio = (1.0 - duty) / duty
        self._slice = slice_seconds
        self._cancel = threading.Event()
        self._sleep = sleep or (lambda seconds: self._cancel.wait(seconds))
        self._clock = clock
        self.rested = 0.0
        self._started = clock()

    def begin_slice(self) -> None:
        self._started = self._clock()

    def rest(self, worked_seconds: float) -> None:
        pause = max(0.0, worked_seconds) * self._ratio
        if pause > 0:
            self.rested += pause
            self._sleep(pause)

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def expired(self) -> bool:
        return self._cancel.is_set() or self._clock() - self._started >= self._slice

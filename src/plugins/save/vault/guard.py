
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class CaptureGuard:

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._captures = 0
        self._exclusive = False

    @contextmanager
    def capturing(self) -> Iterator[None]:
        with self._cond:
            while self._exclusive:
                self._cond.wait()
            self._captures += 1
        try:
            yield
        finally:
            with self._cond:
                self._captures -= 1
                self._cond.notify_all()

    @contextmanager
    def try_exclusive(self) -> Iterator[bool]:
        with self._cond:
            held = not self._exclusive and not self._captures
            if held:
                self._exclusive = True
        try:
            yield held
        finally:
            if held:
                with self._cond:
                    self._exclusive = False
                    self._cond.notify_all()

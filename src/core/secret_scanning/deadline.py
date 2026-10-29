
from __future__ import annotations

import time

SCAN_TIMEOUT_SECONDS: float = 30.0


def _now() -> float:
    return time.monotonic()


class ScanTimeout(Exception):
    pass


class Deadline:

    def __init__(self, seconds: float = SCAN_TIMEOUT_SECONDS) -> None:
        self._end = _now() + seconds

    def check(self) -> None:
        if _now() > self._end:
            raise ScanTimeout()

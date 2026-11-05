
from __future__ import annotations

import time

SCAN_TIMEOUT_SECONDS: float = 30.0


def _now() -> float:
    return time.monotonic()


def _thread_now() -> float:
    return time.thread_time()


class ScanTimeout(Exception):
    pass


class Deadline:

    def __init__(self, seconds: float = SCAN_TIMEOUT_SECONDS) -> None:
        self._end = _now() + seconds

    def check(self) -> None:
        if _now() > self._end:
            raise ScanTimeout()


class CpuDeadline(Deadline):

    def __init__(self, cpu_seconds: float, wall_seconds: float) -> None:
        self._cpu_end = _thread_now() + cpu_seconds
        self._wall_end = _now() + wall_seconds

    def check(self) -> None:
        if _thread_now() > self._cpu_end or _now() > self._wall_end:
            raise ScanTimeout()

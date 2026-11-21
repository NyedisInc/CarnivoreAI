
from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Generic, Optional, Tuple, TypeVar

WINDOW_RETENTION_BYTES: int = 5 * 1024 * 1024

T = TypeVar("T")


@dataclass
class Seen(Generic[T]):

    value: Optional[T] = None
    offset: int = -1

    def set(self, value: Optional[T], offset: int) -> None:
        self.value, self.offset = value, offset

    def within(self, window_start: int) -> Optional[T]:
        return self.value if self.offset >= window_start else None


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICRO = timedelta(microseconds=1)


def _micros(when: datetime) -> int:
    return (when - _EPOCH) // _MICRO


def _from_micros(value: int) -> datetime:
    return _EPOCH + timedelta(microseconds=value)


@dataclass
class SuffixExtreme:

    newest: bool = True
    coverage_start: int = 0
    total: Optional[datetime] = None
    _starts: array = field(default_factory=lambda: array("Q"))
    _times: array = field(default_factory=lambda: array("q"))

    def _beats(self, left: int, right: int) -> bool:
        return left >= right if self.newest else left <= right

    def observe(self, at: Optional[datetime], offset: int) -> None:
        if at is None:
            return
        value = _micros(at)
        if self.total is None or self._beats(value, _micros(self.total)):
            self.total = at
        while self._times and self._beats(value, self._times[-1]):
            self._starts.pop()
            self._times.pop()
        self._starts.append(offset)
        self._times.append(value)

    def trim(self, horizon: int) -> None:
        drop = bisect_left(self._starts, horizon)
        drop = min(drop, max(len(self._starts) - 1, 0))
        if drop:
            del self._starts[:drop], self._times[:drop]

    def within(self, window_start: int) -> Optional[datetime]:
        if window_start <= self.coverage_start:
            return self.total
        index = bisect_left(self._starts, window_start)
        return _from_micros(self._times[index]) if index < len(self._times) else None

    def __len__(self) -> int:
        return len(self._starts)


class RecordStarts:

    _COMPACT_AT = 4096

    def __init__(self, coverage_start: int = 0) -> None:
        self.coverage_start = coverage_start
        self._buf = array("Q")
        self._head = 0

    def __len__(self) -> int:
        return len(self._buf) - self._head

    def add(self, start: int) -> None:
        self._buf.append(start)

    def trim(self, horizon: int) -> None:
        self._head = min(bisect_left(self._buf, horizon, self._head), max(len(self._buf) - 1, self._head))
        if self._head >= self._COMPACT_AT:
            del self._buf[: self._head]
            self._head = 0

    def window_start_at(self, nominal: int, max_scan: int) -> int:
        if nominal <= 0:
            return 0
        if len(self) == 0:
            return max(nominal, self.coverage_start)
        index = max(bisect_right(self._buf, nominal, self._head) - 1, self._head)
        line_start = self._buf[index]
        if line_start == 0:
            return 0 if nominal <= max_scan else nominal
        return line_start if line_start >= nominal - max_scan + 1 else nominal


def newest(coverage_start: int = 0) -> SuffixExtreme:
    return SuffixExtreme(True, coverage_start)


def earliest(coverage_start: int = 0) -> SuffixExtreme:
    return SuffixExtreme(False, coverage_start)


def trim_all(horizon: int, extremes: Tuple[SuffixExtreme, ...], starts: RecordStarts) -> None:
    for extreme in extremes:
        extreme.trim(horizon)
    starts.trim(horizon)


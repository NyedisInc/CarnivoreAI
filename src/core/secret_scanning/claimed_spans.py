
from __future__ import annotations

import bisect
from typing import List, Sequence, Tuple


class ClaimedSpans:

    def __init__(self) -> None:
        self._starts: List[int] = []
        self._ends: List[int] = []

    def overlaps(self, start: int, end: int) -> bool:
        at = bisect.bisect_left(self._starts, end)
        return at > 0 and self._ends[at - 1] > start

    def merge(self, spans: Sequence[Tuple[int, int]]) -> None:
        if any(end <= start for start, end in spans):
            raise ValueError("a claimed span must be non-empty")
        merged = sorted([*zip(self._starts, self._ends), *spans])
        self._starts = [start for start, _ in merged]
        self._ends = [end for _, end in merged]

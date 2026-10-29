
from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from typing import Dict, Literal, Mapping, NamedTuple, Optional, Sequence, Tuple

WindowName = Literal["1h", "5h", "1d", "7d"]
SourceState = Literal["ok", "catching_up", "stats_off", "paused", "plugin_off", "needs_approval", "unavailable"]
PeerWord = Literal["ok", "catching_up", "stats_off", "paused", "plugin_off", "needs_approval", "unavailable",
                   "unreachable", "refused", "not_supported"]

RATE_BACK_S: int = 240


class Classes(NamedTuple):

    fresh: int = 0
    cache_write: int = 0
    cache_read: int = 0
    out: int = 0

    @property
    def tokens_in(self) -> int:
        return self.fresh + self.cache_write + self.cache_read

    def plus(self, other: "Classes") -> "Classes":
        return Classes(*(a + b for a, b in zip(self, other)))


@dataclass(frozen=True)
class WindowSpec:

    name: WindowName
    bucket_s: int
    buckets: int
    grain: Literal["minute", "hour"]


WINDOWS: Mapping[str, WindowSpec] = {
    "1h": WindowSpec("1h", 60, 60, "minute"),
    "5h": WindowSpec("5h", 300, 60, "minute"),
    "1d": WindowSpec("1d", 1800, 48, "minute"),
    "7d": WindowSpec("7d", 10800, 56, "hour"),
}

Gap = Tuple[int, Optional[int]]


def window_start(spec: WindowSpec, now: float) -> int:
    return int(now // spec.bucket_s) * spec.bucket_s - (spec.buckets - 1) * spec.bucket_s


def fold(spec: WindowSpec, now: float, minutes: Mapping[int, Classes], hours: Mapping[int, Classes],
         gaps: Sequence[Gap], data_through: Optional[float]) -> list:
    start = window_start(spec, now)
    rows = minutes if spec.grain == "minute" else hours
    sums: Dict[int, Classes] = {}
    for t, counts in rows.items():
        index = (t - start) // spec.bucket_s
        if 0 <= index < spec.buckets:
            sums[index] = sums.get(index, Classes()).plus(counts)
    bars: list = []
    for index in range(spec.buckets):
        lo = start + index * spec.bucket_s
        hi = lo + spec.bucket_s
        held = data_through is not None and lo > data_through
        disabled = any(s < hi and (e is None or e > lo) for s, e in gaps)
        bars.append(None if held or disabled else sums.get(index, Classes()))
    return bars


def trailing_rate(minutes: Mapping[int, Classes], now: float) -> Dict[str, float]:
    since = int(now // 60) * 60 - RATE_BACK_S
    span = max(now - since, 1.0)
    total = Classes()
    for t, counts in minutes.items():
        if t >= since:
            total = total.plus(counts)
    return {"span_seconds": round(span, 1), "fresh": round(total.fresh / span, 1),
            "cache_write": round(total.cache_write / span, 1), "cache_read": round(total.cache_read / span, 1),
            "out": round(total.out / span, 1)}


def merge(bars: Sequence[Optional[Classes]], others: Sequence[Sequence[Optional[Classes]]]) -> list:
    out: list = []
    for index, own in enumerate(bars):
        parts = [b for b in (own, *(o[index] for o in others)) if b is not None]
        out.append(reduce(Classes.plus, parts) if parts else None)
    return out

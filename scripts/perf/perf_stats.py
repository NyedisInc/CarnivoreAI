
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence


@dataclass
class Percentiles:

    p50: Optional[float]
    p95: Optional[float]
    p99: Optional[float]
    n: int
    min_ms: Optional[float] = field(default=None)
    max_ms: Optional[float] = field(default=None)
    mean_ms: Optional[float] = field(default=None)


def nearest_rank_percentile(samples: Sequence[float], pct: float) -> float:
    if not samples:
        raise ValueError("cannot take a percentile of an empty sample")
    if not (0 < pct <= 100):
        raise ValueError(f"pct must be in (0, 100], got {pct}")
    ordered = sorted(samples)
    rank = math.ceil((pct / 100.0) * len(ordered))
    rank = max(1, min(rank, len(ordered)))
    return ordered[rank - 1]


def summarize(samples: Iterable[float]) -> Percentiles:
    values = list(samples)
    if not values:
        return Percentiles(p50=None, p95=None, p99=None, n=0)
    return Percentiles(
        p50=nearest_rank_percentile(values, 50),
        p95=nearest_rank_percentile(values, 95),
        p99=nearest_rank_percentile(values, 99),
        n=len(values),
        min_ms=min(values),
        max_ms=max(values),
        mean_ms=sum(values) / len(values),
    )


def fmt_ms(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f} ms"


def verdict(p95: Optional[float], target_ms: float) -> str:
    if p95 is None:
        return "N/A (unmeasured)"
    return "PASS" if p95 <= target_ms else "FAIL"


def parse_cputime(text: str) -> float:
    parts = text.strip().split(":")
    if not 2 <= len(parts) <= 3:
        raise ValueError(f"not a cputime: {text!r}")
    total = 0.0
    for part in parts:
        total = total * 60.0 + float(part)
    return total


def idle_cpu_percent(cpu_start_s: float, cpu_end_s: float, wall_s: float) -> float:
    if wall_s <= 0 or cpu_end_s < cpu_start_s:
        raise ValueError("bad idle window")
    return (cpu_end_s - cpu_start_s) / wall_s * 100.0

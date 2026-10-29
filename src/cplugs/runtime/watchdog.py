
from __future__ import annotations

import random
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, NamedTuple, Optional

from src.cplugs.runtime import fsguard

MEMORY_LIMIT_BYTES = 128 * 1024 * 1024
DISK_QUOTA_BYTES = 50 * 1024 * 1024
DISK_QUOTA_FILES = 5000
CPU_FRACTION_LIMIT = 0.20
CPU_WINDOW_SECONDS = 60.0
CRASH_LOOP_STRIKES = 3
CRASH_LOOP_WINDOW_SECONDS = 600.0
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 60.0

BUSY_SAMPLE_SECONDS = 1.0
QUIET_SAMPLE_SECONDS = 10.0
WARMUP_SECONDS = 30.0


class Usage(NamedTuple):

    rss: int
    cpu: float


Sampler = Callable[[int], Optional[Usage]]


@dataclass(frozen=True)
class Verdict:

    ok: bool
    reason: str = ""


def _cpu_from_ps(text: str) -> float:
    days, _, clock = text.rpartition("-")
    total = 0.0
    for part in clock.split(":"):
        total = total * 60 + float(part)
    return total + (int(days) * 86400 if days else 0)


def usage_of(pid: int) -> Optional[Usage]:
    try:
        out = subprocess.run(["/bin/ps", "-o", "rss=,cputime=", "-p", str(int(pid))], capture_output=True, text=True,
                             timeout=2, check=False).stdout.split()
        return Usage(int(out[0]) * 1024, _cpu_from_ps(out[1])) if len(out) == 2 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def next_delay(busy: bool, age: float) -> float:
    return BUSY_SAMPLE_SECONDS if busy or age < WARMUP_SECONDS else QUIET_SAMPLE_SECONDS


def check_memory(usage: Optional[Usage], limit: int = MEMORY_LIMIT_BYTES) -> Verdict:
    if usage is not None and usage.rss > limit:
        return Verdict(False, f"memory {usage.rss} bytes over {limit}")
    return Verdict(True)


def check_disk(files_dir: Path, quota: int = DISK_QUOTA_BYTES, max_files: int = DISK_QUOTA_FILES) -> Verdict:
    used, count = fsguard.tree_usage(files_dir)
    if used > quota:
        return Verdict(False, f"disk {used} bytes over {quota}")
    if count > max_files:
        return Verdict(False, f"{count} files over {max_files}")
    return Verdict(True)


class CpuMeter:

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._samples: Deque[tuple] = deque()

    def sample(self, cpu_seconds: float) -> Verdict:
        now = self._clock()
        self._samples.append((now, cpu_seconds))
        while len(self._samples) > 2 and now - self._samples[1][0] >= CPU_WINDOW_SECONDS:
            self._samples.popleft()
        first = self._samples[0]
        span = now - first[0]
        if span >= CPU_WINDOW_SECONDS and (cpu_seconds - first[1]) / span > CPU_FRACTION_LIMIT:
            return Verdict(False, "cpu over 20 percent of one core for a minute")
        return Verdict(True)


class StrikeLedger:

    def __init__(self, clock: Callable[[], float] = time.monotonic, rng: Callable[[], float] = random.random) -> None:
        self._clock = clock
        self._rng = rng
        self._times: Deque[float] = deque()

    def strike(self) -> bool:
        now = self._clock()
        self._times.append(now)
        while self._times and now - self._times[0] > CRASH_LOOP_WINDOW_SECONDS:
            self._times.popleft()
        return len(self._times) >= CRASH_LOOP_STRIKES

    def backoff(self) -> float:
        ceiling = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(len(self._times) - 1, 0)))
        return self._rng() * ceiling

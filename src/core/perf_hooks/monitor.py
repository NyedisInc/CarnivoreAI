"""The developer performance monitor: counters, the loop-lag sampler, the publisher.

Description: OFF BY DEFAULT AND NEAR FREE WHILE OFF. Every recording seam in
  the app (the request log, both socket writers, the terminal input path,
  the attention watcher) calls one `record_*` method whose first statement
  is `if not self.enabled: return`, and no task, timer or subprocess exists
  until the monitor is enabled. Turning it off cancels the task and drops
  every counter.

  While ON it keeps a rolling minute of counters in twelve five-second
  buckets and, every five seconds, PUSHES one `perf.sample` frame over
  `/ws/events` (one broadcast for every connected browser, never a poll):

  - event-loop lag: a coroutine asks to sleep `LAG_TICK_SECONDS` and
    records how late it woke. Lateness is time the loop (or the GIL) was
    held by something else, which is exactly the delay a keystroke frame
    waits before its handler runs.
  - HTTP requests per route template: count and total handler time.
  - socket traffic per channel (`events`, `terminal_out`, `terminal_in`),
    per topic (frame type) and per client: messages and bytes.
  - CPU and memory of this process and of every tmux server
    (`process_stats.py`).
  - the attention watcher's pass duration, full and targeted apart.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import structlog

from src.core.perf_hooks.process_stats import ProcessSampler, ProcessStatsError

logger = structlog.get_logger()

LAG_TICK_SECONDS = 0.1
PUBLISH_SECONDS = 5.0
BUCKETS = 12
TOP_N = 15
FRAME_TYPE = "perf.sample"
STALL_MS = 30.0

Publish = Callable[[Dict[str, Any]], int]

_TYPE_KEY = '"type": "'


def frame_topic(text: str) -> str:
    at = text.find(_TYPE_KEY, 0, 200)
    if at < 0:
        return "text"
    start = at + len(_TYPE_KEY)
    end = text.find('"', start, start + 64)
    return text[start:end] if end > start else "text"


@dataclass
class _Bucket:

    routes: Dict[Tuple[str, str], List[float]] = field(default_factory=dict)
    ws: Dict[Tuple[str, str], List[int]] = field(default_factory=dict)
    ws_clients: Dict[Tuple[str, str], List[int]] = field(default_factory=dict)
    lag_ms: List[float] = field(default_factory=list)
    watcher_ms: Dict[str, List[float]] = field(default_factory=dict)


def _quantile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 2)


class PerfMonitor:

    def __init__(self, *, sampler: Optional[ProcessSampler] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.enabled = False
        self._clock = clock
        self._sampler = sampler or ProcessSampler()
        self._buckets: Deque[_Bucket] = deque([_Bucket()], maxlen=BUCKETS)
        self._task: Optional[asyncio.Task] = None
        self._publish: Optional[Publish] = None
        self._enabled_at: Optional[float] = None
        self._last_frame: Optional[Dict[str, Any]] = None


    def record_request(self, method: str, route: str, duration_ms: float) -> None:
        if not self.enabled:
            return
        cell = self._buckets[-1].routes.setdefault((method, route), [0, 0.0])
        cell[0] += 1
        cell[1] += duration_ms

    def record_ws(self, channel: str, topic: str, nbytes: int, client: str) -> None:
        if not self.enabled:
            return
        bucket = self._buckets[-1]
        cell = bucket.ws.setdefault((channel, topic), [0, 0])
        cell[0] += 1
        cell[1] += nbytes
        per_client = bucket.ws_clients.setdefault((channel, client), [0, 0])
        per_client[0] += 1
        per_client[1] += nbytes

    def record_watcher_pass(self, seconds: float, kind: str) -> None:
        if not self.enabled:
            return
        self._buckets[-1].watcher_ms.setdefault(kind, []).append(seconds * 1000.0)


    def enable(self, publish: Optional[Publish]) -> None:
        self._publish = publish
        if self.enabled:
            return
        self.enabled = True
        self._enabled_at = self._clock()
        self._buckets = deque([_Bucket()], maxlen=BUCKETS)
        self._task = asyncio.get_running_loop().create_task(self._run(), name="perf-hooks")
        logger.info("perf_hooks_enabled")

    def disable(self) -> None:
        if not self.enabled:
            return
        self.enabled = False
        if self._task is not None:
            self._task.cancel()
        self._task = None
        self._buckets = deque([_Bucket()], maxlen=BUCKETS)
        self._last_frame = None
        self._enabled_at = None
        logger.info("perf_hooks_disabled")

    @property
    def last_frame(self) -> Optional[Dict[str, Any]]:
        return self._last_frame


    async def _run(self) -> None:
        next_publish = self._clock() + PUBLISH_SECONDS
        while self.enabled:
            asked = self._clock()
            await asyncio.sleep(LAG_TICK_SECONDS)
            woke = self._clock()
            self._buckets[-1].lag_ms.append(max(0.0, (woke - asked - LAG_TICK_SECONDS) * 1000.0))
            if woke >= next_publish:
                next_publish = woke + PUBLISH_SECONDS
                await self.publish_now()

    async def publish_now(self) -> Dict[str, Any]:
        try:
            processes: Optional[Dict[str, object]] = await asyncio.to_thread(self._sampler.sample)
        except ProcessStatsError as exc:
            logger.warning("perf_hooks_ps_failed", error=str(exc))
            processes = None
        frame = self.build_frame(processes)
        self._last_frame = frame
        self._buckets.append(_Bucket())
        if self._publish is not None:
            self._publish(frame)
        return frame

    def build_frame(self, processes: Optional[Dict[str, object]]) -> Dict[str, Any]:
        buckets = list(self._buckets)
        window_s = max(PUBLISH_SECONDS, min(len(buckets) * PUBLISH_SECONDS,
                                            self._clock() - (self._enabled_at or self._clock())))
        per_min = 60.0 / window_s
        latest_lag = buckets[-1].lag_ms
        all_lag = [v for b in buckets for v in b.lag_ms]

        routes: Dict[Tuple[str, str], List[float]] = {}
        ws: Dict[Tuple[str, str], List[int]] = {}
        clients: Dict[Tuple[str, str], List[int]] = {}
        watcher: Dict[str, List[float]] = {}
        for b in buckets:
            for key, (n, ms) in b.routes.items():
                cell = routes.setdefault(key, [0, 0.0]); cell[0] += n; cell[1] += ms
            for key, (n, nb) in b.ws.items():
                cell = ws.setdefault(key, [0, 0]); cell[0] += n; cell[1] += nb
            for key, (n, nb) in b.ws_clients.items():
                cell = clients.setdefault(key, [0, 0]); cell[0] += n; cell[1] += nb
            for kind, values in b.watcher_ms.items():
                watcher.setdefault(kind, []).extend(values)

        busiest = sorted(routes.items(), key=lambda kv: -kv[1][1])[:TOP_N]
        return {
            "type": FRAME_TYPE,
            "window_s": round(window_s, 1),
            "loop_lag_ms": {
                "p50": _quantile(latest_lag, 0.5), "p99": _quantile(latest_lag, 0.99),
                "max": round(max(latest_lag), 2) if latest_lag else None,
                "minute_max": round(max(all_lag), 2) if all_lag else None,
                "stalls_per_min": round(sum(v >= STALL_MS for v in all_lag) * per_min, 1),
            },
            "requests_per_min": round(sum(n for n, _ in routes.values()) * per_min, 1),
            "routes": [{"method": m, "route": r, "per_min": round(n * per_min, 1),
                        "avg_ms": round(ms / n, 1), "busy_pct": round(ms / 1000.0 / window_s * 100.0, 2)}
                       for (m, r), (n, ms) in busiest],
            "ws": [{"channel": c, "topic": t, "per_min": round(n * per_min, 1),
                    "bytes_per_s": round(nb / window_s, 1)}
                   for (c, t), (n, nb) in sorted(ws.items(), key=lambda kv: -kv[1][1])[:TOP_N]],
            "ws_clients": [{"channel": c, "client": k, "per_min": round(n * per_min, 1),
                            "bytes_per_s": round(nb / window_s, 1)}
                           for (c, k), (n, nb) in sorted(clients.items(), key=lambda kv: -kv[1][1])[:TOP_N]],
            "watcher_ms": {kind: {"passes_per_min": round(len(v) * per_min, 1), "p50": _quantile(v, 0.5),
                                  "max": round(max(v), 2)} for kind, v in watcher.items() if v},
            "processes": processes,
        }


PERF = PerfMonitor()

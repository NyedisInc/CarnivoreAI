
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Set, Tuple

import structlog

logger = structlog.get_logger()

MIN_INTERVAL_SECONDS = 5
TickFn = Callable[[str, str, int], Awaitable[None]]


class TimerScheduler:

    def __init__(self, send_tick: TickFn, *, min_interval: int = MIN_INTERVAL_SECONDS,
                 clock: Callable[[], float] = time.time) -> None:
        self._send_tick = send_tick
        self._min_interval = max(1, int(min_interval))
        self._clock = clock
        self._loops: Dict[str, List[asyncio.Task[Any]]] = {}
        self._tick_tasks: Dict[str, Set[asyncio.Task[Any]]] = {}
        self._inflight: Set[Tuple[str, str]] = set()
        self._stopped = False

    def arm(self, plugin_id: str, timers: Mapping[str, int]) -> int:
        self.cancel_for(plugin_id)
        if self._stopped or not timers:
            return 0
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return 0
        tasks: List[asyncio.Task[Any]] = []
        for name, raw_interval in timers.items():
            if not isinstance(name, str) or not name:
                continue
            interval = max(int(raw_interval), self._min_interval)
            tasks.append(loop.create_task(self._run_loop(plugin_id, name, interval)))
        if tasks:
            self._loops[plugin_id] = tasks
        return len(tasks)

    def in_flight(self, plugin_id: str, name: str) -> bool:
        return (plugin_id, name) in self._inflight

    def active_count(self, plugin_id: str) -> int:
        return len(self._loops.get(plugin_id, ()))

    async def _run_loop(self, plugin_id: str, name: str, interval: int) -> None:
        try:
            while not self._stopped:
                await asyncio.sleep(interval)
                if self._stopped:
                    return
                key = (plugin_id, name)
                if key in self._inflight:
                    logger.debug("cplug_timer_coalesced", cplug=plugin_id, timer=name)
                    continue
                self._inflight.add(key)
                scheduled_for = int(self._clock())
                task = asyncio.create_task(self._dispatch_one(plugin_id, name, scheduled_for))
                bucket = self._tick_tasks.setdefault(plugin_id, set())
                bucket.add(task)
                task.add_done_callback(lambda t, p=plugin_id: self._tick_tasks.get(p, set()).discard(t))
        except asyncio.CancelledError:
            return

    async def _dispatch_one(self, plugin_id: str, name: str, scheduled_for: int) -> None:
        key = (plugin_id, name)
        try:
            await self._send_tick(plugin_id, name, scheduled_for)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("cplug_timer_tick_failed", cplug=plugin_id, timer=name, error_type=type(exc).__name__)
        finally:
            self._inflight.discard(key)

    def cancel_for(self, plugin_id: str) -> int:
        loops = self._loops.pop(plugin_id, [])
        for task in loops:
            task.cancel()
        ticks = self._tick_tasks.pop(plugin_id, set())
        for task in ticks:
            task.cancel()
        for key in [k for k in self._inflight if k[0] == plugin_id]:
            self._inflight.discard(key)
        return len(loops)

    async def stop_all(self) -> None:
        self._stopped = True
        pending: List[asyncio.Task[Any]] = []
        for plugin_id in list(self._loops):
            pending.extend(self._loops.pop(plugin_id, []))
        for plugin_id in list(self._tick_tasks):
            pending.extend(self._tick_tasks.pop(plugin_id, set()))
        self._inflight.clear()
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


from __future__ import annotations

import asyncio
import sqlite3
import time
from typing import Any, Callable, List, Optional

import structlog

from src.cplugs.huddle import fire, inbox, inbox_delivery, service, triggers
from src.cplugs.huddle.wait_runner import WaitRunner
from src.cplugs.huddle.inbox_store import InboxStore
from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.sdk import CplugContext

logger = structlog.get_logger()

MAX_SLEEP_S = 300.0
MIN_SLEEP_S = 0.05

DELIVERY_ERRORS = (fire.FireFailed, OSError, RuntimeError, ValueError, LookupError, AttributeError, sqlite3.Error)


class Scheduler:

    def __init__(self, ctx: CplugContext, clock: Callable[[], float] = time.time) -> None:
        self._ctx = ctx
        self._clock = clock
        self._wake = asyncio.Event()
        self._deliveries: set = set()
        self._waits = WaitRunner(ctx, clock)
        self._check_task: Optional["asyncio.Task[int]"] = None
        self._wrote = True

    def nudge(self) -> None:
        self._wake.set()

    def wrote(self) -> None:
        self._wrote = True
        self._wake.set()

    async def waits_due(self) -> int:
        events, self._wrote = self._wrote, False
        worked = await self._waits.run_pass(events=events, checks=False)
        if self._check_task is None or self._check_task.done():
            task = self._check_task = asyncio.get_running_loop().create_task(self._waits.run_checks_safe(), name="huddle-wait-checks")
            task.add_done_callback(self._checks_done)
        return worked

    def _checks_done(self, task: "asyncio.Task[int]") -> None:
        if task.cancelled():
            return
        if task.exception() is None and task.result() == 0:
            return
        self._wake.set()

    def _checks_running(self) -> bool:
        return self._check_task is not None and not self._check_task.done()

    async def fire_due(self) -> int:
        store = service.store(self._ctx)
        items = await asyncio.to_thread(store.claim_due_triggers)
        if items:
            await asyncio.gather(*(self._deliver(store, item) for item in items))
        return len(items)

    async def inbox_due(self) -> int:
        store = InboxStore(service.store(self._ctx))
        if not await asyncio.to_thread(store.has_open):
            return 0
        return await inbox_delivery.deliver_pass(self._ctx, self._clock)

    async def _deliver(self, store: Any, item: dict) -> None:
        try:
            outcome = await fire.deliver(self._ctx, item)
            logger.info("task_manager_scheduled_fired", item=item["id"], list=item["list"], outcome=outcome)
        except DELIVERY_ERRORS as exc:
            message = str(exc) if isinstance(exc, fire.FireFailed) else f"{type(exc).__name__}: {exc}"
            await asyncio.to_thread(store.record_trigger_error, item["id"], message)

    async def run_now(self, item_id: int) -> dict:
        store = service.store(self._ctx)
        item = await asyncio.to_thread(store.claim_now, item_id)
        await self._deliver(store, item)
        return await asyncio.to_thread(store.item, item_id)

    def _timeout(self) -> Optional[float]:
        due = service.store(self._ctx).next_trigger_due()
        if InboxStore(service.store(self._ctx)).has_open():
            due = self._clock() + inbox.POLL_S if due is None else min(due, self._clock() + inbox.POLL_S)
        waiting = self._waits.next_due(include_checks=not self._checks_running())
        if waiting is not None:
            due = waiting if due is None else min(due, waiting)
        if due is None:
            return None
        return min(max(due - self._clock(), MIN_SLEEP_S), MAX_SLEEP_S)

    async def run(self) -> None:
        try:
            await self._ctx.sessions.booted()
        except (OSError, RuntimeError, AttributeError) as exc:
            logger.warning("task_manager_schedule_boot_wait_failed", error=str(exc))
        while True:
            self._wake.clear()
            try:
                await self.fire_due()
                await self.inbox_due()
                await self.waits_due()
                timeout = await asyncio.to_thread(self._timeout)
            except (OSError, RuntimeError, sqlite3.Error) as exc:
                logger.error("task_manager_schedule_pass_failed", error_type=type(exc).__name__, error=str(exc)[:200])
                timeout = MAX_SLEEP_S
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except asyncio.TimeoutError:
                pass


_task: Optional["asyncio.Task[None]"] = None
_unsubscribe: Optional[Callable[[], None]] = None
_unsubscribe_writes: Optional[Callable[[], None]] = None
_scheduler: Optional[Scheduler] = None


async def run_now(item_id: int) -> dict:
    if _scheduler is None:
        raise TaskManagerInvalid("the scheduler is not running; the huddle plugin is off")
    return await _scheduler.run_now(item_id)


def _poke_write(loop: "asyncio.AbstractEventLoop", scheduler: Scheduler) -> None:
    try:
        loop.call_soon_threadsafe(scheduler.wrote)
    except RuntimeError as exc:
        logger.debug("task_manager_schedule_write_poke_loop_closed", error=str(exc))


def _poke(loop: "asyncio.AbstractEventLoop", scheduler: Scheduler) -> None:
    try:
        loop.call_soon_threadsafe(scheduler.nudge)
    except RuntimeError as exc:
        logger.debug("task_manager_schedule_poke_loop_closed", error=str(exc))


def start(ctx: CplugContext) -> None:
    global _task, _unsubscribe, _unsubscribe_writes, _scheduler
    stop()
    scheduler = _scheduler = Scheduler(ctx)
    loop = asyncio.get_running_loop()
    _unsubscribe = triggers.subscribe(lambda: _poke(loop, scheduler))
    _unsubscribe_writes = triggers.subscribe_writes(lambda: _poke_write(loop, scheduler))
    _task = loop.create_task(scheduler.run(), name="huddle-scheduler")


def stop() -> None:
    global _task, _unsubscribe, _unsubscribe_writes, _scheduler
    if _scheduler is not None and _scheduler._check_task is not None:
        _scheduler._check_task.cancel()
    _scheduler = None
    if _unsubscribe_writes is not None:
        _unsubscribe_writes()
        _unsubscribe_writes = None
    if _unsubscribe is not None:
        _unsubscribe()
        _unsubscribe = None
    if _task is not None:
        _task.cancel()
        _task = None

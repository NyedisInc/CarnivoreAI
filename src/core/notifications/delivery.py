
from __future__ import annotations

import asyncio
import collections
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Deque, Optional

import structlog

from src.core.notifications.contracts import DeliveryResult, FailureClass, NotifyEvent
from src.core.notifications.routing_view import DestinationView
from src.core.notifications.sms_cap import SmsDayCount

log = structlog.get_logger(__name__)

QUEUE_MAX = 50
PER_MINUTE = 20
PER_DAY_SMS = 20
MINUTE = 60.0
RETRY_DELAYS = (1.0, 4.0)
RETRY_AFTER_CAP = 20.0


@dataclass(frozen=True)
class Item:

    dest: DestinationView
    event: NotifyEvent
    recheck_open: bool = False


Attempt = Callable[[Item], Awaitable[DeliveryResult]]
OnResult = Callable[[Item, DeliveryResult], Awaitable[None]]
Sleep = Callable[[float], Awaitable[Any]]
Recipients = Callable[[Item], Awaitable[int]]
Admit = Callable[[Item], Optional[Item]]
SMS_CAP_DETAIL = "daily sms cap"


def retry_delay(result: DeliveryResult, attempt_index: int) -> float:
    if result.failure is FailureClass.RATE_LIMITED and result.retry_after is not None:
        return max(0.0, min(float(result.retry_after), RETRY_AFTER_CAP))
    return RETRY_DELAYS[attempt_index]


class Lane:

    def __init__(self, dest_id: str, *, sms_like: bool, clock: Callable[[], float], sleep: Sleep,
                 attempt: Attempt, on_result: OnResult, recipients: Optional[Recipients] = None,
                 admit: Optional[Admit] = None, day_count: Optional[SmsDayCount] = None) -> None:
        self.dest_id = dest_id
        self._sms_like = sms_like
        self._clock = clock
        self._sleep = sleep
        self._attempt = attempt
        self._on_result = on_result
        self._recipients = recipients
        self._admit = admit
        self._queue: Deque[Item] = collections.deque()
        self._minute: Deque[float] = collections.deque()
        self._day_count = day_count if day_count is not None else SmsDayCount()
        self._task: Optional[asyncio.Task] = None

    def enqueue(self, item: Item) -> bool:
        dropped = len(self._queue) >= QUEUE_MAX
        if dropped:
            self._queue.popleft()
            log.warning("notify_queue_overflow", dest=self.dest_id, cap=QUEUE_MAX)
        self._queue.append(item)
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())
        return dropped

    @property
    def pending(self) -> int:
        return len(self._queue)

    async def join(self) -> None:
        task = self._task
        if task is not None and not task.done():
            await task

    def clear(self) -> None:
        self._queue.clear()

    def cancel(self) -> Optional[asyncio.Task]:
        self._queue.clear()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            return self._task
        return None

    async def _run(self) -> None:
        while self._queue:
            await self._wait_for_minute_slot()
            queued = self._queue.popleft()
            item = self._admitted(queued)
            if item is None:
                continue
            now = self._clock()
            billed = await self._billed(item) if self._sms_like else 0
            if self._sms_like and not self._charge(now, billed):
                log.warning("notify_sms_daily_cap", dest=self.dest_id, cap=PER_DAY_SMS, needed=billed,
                            left=self._sms_left(now))
                await self._on_result(item, DeliveryResult(
                    ok=False, failure=FailureClass.RATE_LIMITED,
                    detail=f"{SMS_CAP_DETAIL}: {billed} messages needed, {self._sms_left(now)} left today"))
                continue
            self._minute.append(now)
            result = await self._deliver(item, billed)
            await self._on_result(item, result)

    def _admitted(self, item: Item) -> Optional[Item]:
        if self._admit is None:
            return item
        live = self._admit(item)
        if live is None:
            log.info("notify_dropped_before_send", dest=self.dest_id, type_id=item.event.type_id)
        return live

    async def _wait_for_minute_slot(self) -> None:
        while True:
            now = self._clock()
            while self._minute and now - self._minute[0] >= MINUTE:
                self._minute.popleft()
            if len(self._minute) < PER_MINUTE:
                return
            await self._sleep(MINUTE - (now - self._minute[0]))

    async def _billed(self, item: Item) -> int:
        return await self._recipients(item) if self._recipients is not None else 1

    def _day_key(self, now: float) -> str:
        return datetime.fromtimestamp(now).strftime("%Y-%m-%d")

    def _sms_left(self, now: float) -> int:
        return max(PER_DAY_SMS - self._day_count.used(self.dest_id, self._day_key(now)), 0)

    def _charge(self, now: float, billed: int) -> bool:
        if billed > self._sms_left(now):
            return False
        self._day_count.add(self.dest_id, self._day_key(now), billed)
        return True

    async def send_now(self, item: Item) -> DeliveryResult:
        if self._sms_like:
            now = self._clock()
            billed = await self._billed(item)
            if not self._charge(now, billed):
                log.warning("notify_sms_daily_cap", dest=self.dest_id, cap=PER_DAY_SMS, needed=billed, test=True)
                return DeliveryResult(ok=False, failure=FailureClass.RATE_LIMITED,
                                      detail=f"{SMS_CAP_DETAIL}: {billed} messages needed, {self._sms_left(now)} left today")
        return await self._attempt(item)

    async def _deliver(self, item: Item, billed: int = 0) -> DeliveryResult:
        result = await self._attempt(item)
        for index in range(len(RETRY_DELAYS)):
            if result.ok or not result.retryable:
                break
            await self._sleep(retry_delay(result, index))
            live = self._admitted(item)
            if live is None:
                break
            item = live
            if self._sms_like and not self._charge(self._clock(), billed):
                log.warning("notify_sms_daily_cap", dest=self.dest_id, cap=PER_DAY_SMS, needed=billed, retry=True)
                break
            result = await self._attempt(item)
        return result

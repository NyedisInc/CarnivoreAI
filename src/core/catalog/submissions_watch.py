
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import structlog
from fastapi import HTTPException, Request

from src.core import resource_push
from src.core.catalog import catalog_auth
from src.core.resource_push import topics

logger = structlog.get_logger()

FAST_SECONDS = 20.0
SLOW_SECONDS = 120.0
BACKOFF_SECONDS = 900.0
STALE_AFTER_SECONDS = 60.0
MIN_FORCE_GAP_SECONDS = 10.0

_OPEN_STATUSES = frozenset({"pending", "approved", "publishing"})
_FAST_GATE_STATES = frozenset({"received", "gating"})
_SIGNED_OUT_STATUS = 403

Reader = Callable[[], Awaitable[Dict[str, Any]]]
Signature = frozenset


def _events_len(item: Dict[str, Any]) -> int:
    events = item.get("events")
    return len(events) if isinstance(events, list) else 0


def _rows(body: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = body.get("submissions") if isinstance(body, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def signature(body: Optional[Dict[str, Any]]) -> Signature:
    return frozenset(
        (str(r.get("submission_id", "")), str(r.get("status", "")), str(r.get("gate_state", "")), _events_len(r))
        for r in _rows(body)
    )


def open_delay(body: Optional[Dict[str, Any]]) -> Optional[float]:
    delay: Optional[float] = None
    for item in _rows(body):
        if item.get("status") not in _OPEN_STATUSES:
            continue
        fast = item.get("status") == "pending" and item.get("gate_state") in _FAST_GATE_STATES
        if fast:
            return FAST_SECONDS
        delay = SLOW_SECONDS
    return delay


class SubmissionsWatch:

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        notify: Callable[[str], None] = resource_push.notify,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock = clock
        self._notify = notify
        self._sleep = sleep
        self._body: Optional[Dict[str, Any]] = None
        self._sig: Optional[Signature] = None
        self._read_at: float = 0.0
        self._limited_until: float = 0.0
        self._failed = False
        self._lock = asyncio.Lock()
        self._epoch = 0
        self._poller: Optional["asyncio.Task[None]"] = None
        self._tasks: Set["asyncio.Task[None]"] = set()

    @property
    def poller(self) -> Optional["asyncio.Task[None]"]:
        return self._poller

    @property
    def running(self) -> bool:
        return self._poller is not None and not self._poller.done()

    def next_delay(self) -> Optional[float]:
        delay = open_delay(self._body)
        if delay is None:
            return None
        remaining = self._limited_until - self._clock()
        if remaining > 0:
            return remaining
        return max(delay, SLOW_SECONDS) if self._failed else delay

    async def _refresh(self, reader: Reader) -> Dict[str, Any]:
        async with self._lock:
            epoch = self._epoch
            try:
                body = await reader()
            except HTTPException as exc:
                if exc.status_code == _SIGNED_OUT_STATUS:
                    self._body, self._sig, self._failed = None, None, False
                elif exc.status_code == 429:
                    self._limited_until = self._clock() + BACKOFF_SECONDS
                else:
                    self._failed = True
                raise
            if epoch != self._epoch:
                return body
            self._failed = False
            self._limited_until = 0.0
            self._body, self._read_at = body, self._clock()
            sig = signature(body)
            changed = sig != self._sig
            self._sig = sig
        if changed:
            self._notify(topics.CATALOG_SUBMISSIONS)
        return body

    def session_changed(self, event: Dict[str, Any]) -> None:
        self._epoch += 1
        self._body, self._sig, self._failed, self._limited_until = None, None, False, 0.0
        self._notify(topics.CATALOG_SUBMISSIONS)

    async def poll_once(self, reader: Reader) -> None:
        try:
            await self._refresh(reader)
        except HTTPException as exc:
            logger.info("catalog_submissions_read_refused", status=exc.status_code)

    async def _run(self, reader: Reader) -> None:
        while True:
            delay = self.next_delay()
            if delay is None:
                return
            await self._sleep(delay)
            await self.poll_once(reader)

    def _ensure_running(self, reader: Reader) -> None:
        """Start the poller when a row is open and it is not already running."""
        if not self.running and self.next_delay() is not None:
            self._poller = asyncio.get_running_loop().create_task(self._run(reader))

    def _spawn(self, work: Awaitable[None]) -> None:
        task = asyncio.get_running_loop().create_task(work)  # type: ignore[arg-type]
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def mine(self, reader: Reader, *, force: bool = False) -> Dict[str, Any]:
        now = self._clock()
        limited = now < self._limited_until
        if self._body is None:
            if limited:
                raise HTTPException(
                    status_code=429, detail={"code": "rate_limited", "detail": "too many reads of your submissions"}
                )
            body = await self._refresh(reader)
        else:
            body = self._body
            age = now - self._read_at
            if not limited and (age > STALE_AFTER_SECONDS or (force and age >= MIN_FORCE_GAP_SECONDS)):
                if force:
                    body = await self._refresh(reader)
                elif not self._tasks:
                    self._spawn(self.poll_once(reader))
        self._ensure_running(reader)
        return body

    def after_write(self, reader: Reader) -> None:
        self._read_at = float("-inf")

        async def work() -> None:
            await self.poll_once(reader)
            self._ensure_running(reader)

        self._spawn(work())


def watch_for(request: Request) -> SubmissionsWatch:
    watch = getattr(request.app.state, "submissions_watch", None)
    if watch is None:
        watch = SubmissionsWatch()
        catalog_auth.subscribe(watch.session_changed)
        request.app.state.submissions_watch = watch
    return watch


async def read_mine(request: Request) -> Dict[str, Any]:
    from src.api.catalog_hosted_routes import _hosted, _relay  # noqa: PLC0415
    from src.api.catalog_rating_routes import _bearer  # noqa: PLC0415

    return _relay(await _hosted(request, "GET", "/submissions/mine", bearer=await _bearer(request)))


def reader_for(request: Request) -> Reader:
    async def read() -> Dict[str, Any]:
        return await read_mine(request)

    return read


def after_write(request: Request) -> None:
    watch_for(request).after_write(reader_for(request))

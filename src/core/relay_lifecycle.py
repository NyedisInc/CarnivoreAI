
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional

import structlog

from src.core import relay_publisher
from src.core.catalog import catalog_auth

logger = structlog.get_logger()

CONNECT_TIMEOUT_SECONDS = 15.0

DRAIN_SECONDS = 5.0

NOT_RUNNING = "the relay publisher is not running"


class RelayUnavailable(Exception):

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RelayLifecycle:

    def __init__(
        self,
        *,
        start: Callable[[], Optional[Any]],
        has_live_links: Callable[[], Awaitable[bool]],
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        drain_seconds: float = DRAIN_SECONDS,
    ) -> None:
        self._start = start
        self._has_live_links = has_live_links
        self._connect_timeout = connect_timeout
        self._drain = drain_seconds
        self._publisher: Optional[Any] = None
        self._lock = asyncio.Lock()
        self._holds = 0
        self._stop_task: Optional[asyncio.Task] = None
        self._recheck = False
        self._draining: Optional[Any] = None
        self._unstartable = False
        self._account_task: Optional[asyncio.Task] = None

    def on_account_event(self, event: dict) -> None:
        try:
            self._account_task = asyncio.get_running_loop().create_task(
                self._account_changed(bool(event.get("signed_in"))))
        except RuntimeError:
            logger.warning("relay_account_event_without_loop")

    async def _account_changed(self, signed_in: bool) -> None:
        publisher = self._publisher
        if publisher is not None:
            publisher.on_account_change()
        elif signed_in:
            await self.start_if_live()

    @property
    def publisher(self) -> Optional[Any]:
        return self._publisher

    @property
    def available(self) -> bool:
        if self._publisher is None:
            return not self._unstartable
        return bool(self._publisher.connected)

    def _build(self) -> Optional[Any]:
        self._publisher = self._start()
        self._unstartable = self._publisher is None
        return self._publisher

    async def start_if_live(self) -> None:
        if not await self._has_live_links():
            logger.info("relay_publish_quiet", reason="no_live_links")
            return
        async with self._lock:
            if self._publisher is None:
                self._build()

    @asynccontextmanager
    async def connected(self) -> AsyncIterator[Any]:
        self._holds += 1
        try:
            async with self._lock:
                publisher = self._publisher or self._build()
            if publisher is None:
                raise RelayUnavailable(NOT_RUNNING)
            if not await publisher.wait_connected(self._connect_timeout):
                raise RelayUnavailable(publisher.status)
            yield publisher
        finally:
            self._holds -= 1
            self.schedule_stop_check()

    def schedule_stop_check(self) -> None:
        if self._publisher is None:
            return
        self._recheck = True
        if self._stop_task is None or self._stop_task.done():
            self._stop_task = asyncio.create_task(self._stop_checks())
            self._stop_task.add_done_callback(_report_stop_end)

    async def _stop_checks(self) -> None:
        while self._recheck:
            self._recheck = False
            await self.stop_if_idle()

    async def stop_if_idle(self) -> None:
        async with self._lock:
            publisher = self._publisher
            if publisher is None or self._holds or publisher.stopped:
                return
            if await self._has_live_links():
                return
            self._publisher = None
            self._draining = publisher
            try:
                await publisher.aclose(drain_seconds=self._drain)
            finally:
                self._draining = None
        logger.info("relay_publish_idle_closed")

    async def aclose(self) -> None:
        catalog_auth.unsubscribe(self.on_account_event)
        if self._account_task is not None:
            self._account_task.cancel()
        draining = self._draining
        if self._stop_task is not None:
            self._stop_task.cancel()
            await asyncio.gather(self._stop_task, return_exceptions=True)
        publisher, self._publisher = self._publisher, None
        for running in (draining, publisher):
            if running is not None:
                await running.aclose()


def _report_stop_end(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("relay_publish_stop_check_failed",
                     error=type(task.exception()).__name__)


class _EmptySetWatch:

    def __init__(self, store: Any, on_empty: Callable[[], None]) -> None:
        self._store = store
        self._on_empty = on_empty

    async def live_relay_declarations(self) -> List[Any]:
        rows = await self._store.live_relay_declarations()
        if not rows:
            self._on_empty()
        return rows


def build(
    config: Any, *, registry: Any, store: Any, db_path: Optional[Path] = None,
    version: str = "", account: Optional[Any] = None,
) -> Optional[RelayLifecycle]:
    if not config.enabled:
        return None

    async def has_live_links() -> bool:
        return bool(await store.live_expiry_by_session())

    def start() -> Optional[Any]:
        return relay_publisher.start_if_enabled(
            config, registry=registry,
            store=_EmptySetWatch(store, lifecycle.schedule_stop_check),
            db_path=db_path, version=version, account=account)

    lifecycle = RelayLifecycle(start=start, has_live_links=has_live_links)
    if account is not None:
        catalog_auth.subscribe(lifecycle.on_account_event)
    return lifecycle


from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.listing_push.diff import KeyedRows, diff, keyed

logger = structlog.get_logger()

FRAME_TYPE = "listing.delta"

WAKE_FRAME_TYPES = frozenset({"session.status", "sessions.changed", "session.renamed"})

DEFAULT_BACKSTOP_SECONDS = 5.0

EVENT_BACKSTOP_SECONDS = 60.0

DEFAULT_MIN_INTERVAL_SECONDS = 0.5

DEFAULT_STALE_SECONDS = 2.0


@dataclass
class CollectionResult:

    rows: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    status: Optional[int] = None
    detail: Any = None

    def status_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "status": self.status, "detail": self.detail, "meta": self.meta}


@dataclass
class Collection:

    name: str
    build: Callable[[Dict[str, Any]], Awaitable[CollectionResult]]
    key_of: Callable[[Dict[str, Any]], Optional[str]]


class ListingPublisher:

    def __init__(
        self,
        collections: List[Collection],
        publish: Callable[[Dict[str, Any]], int],
        client_count: Callable[[], int],
        *,
        backstop_seconds: float = DEFAULT_BACKSTOP_SECONDS,
        min_interval: float = DEFAULT_MIN_INTERVAL_SECONDS,
        stale_seconds: float = DEFAULT_STALE_SECONDS,
        after_pass: Optional[Callable[[], None]] = None,
        feed: Optional[Callable[[], Awaitable[bool]]] = None,
    ) -> None:
        self._collections = list(collections)
        self._publish = publish
        self._client_count = client_count
        self.backstop_seconds = backstop_seconds
        self.min_interval = min_interval
        self.stale_seconds = stale_seconds
        self._after_pass = after_pass
        self._feed = feed
        self.stream = secrets.token_hex(6)
        self.seq = 0
        self._rows: Dict[str, KeyedRows] = {}
        self._status: Dict[str, Dict[str, Any]] = {}
        self._computed_at: Optional[float] = None
        self._inflight: Optional["asyncio.Future[Optional[Dict[str, Any]]]"] = None
        self._wake = asyncio.Event()
        self.passes = 0
        self.last_pass_seconds = 0.0


    def wake(self) -> None:
        self._wake.set()

    def on_hub_publish(self, frame_type: Optional[str]) -> None:
        if frame_type in WAKE_FRAME_TYPES:
            self._wake.set()


    async def run_pass(self) -> Optional[Dict[str, Any]]:
        task = self._inflight
        if task is None or task.done():
            task = asyncio.ensure_future(self._pass_body())
            self._inflight = task
        return await asyncio.shield(task)

    async def _pass_body(self) -> Optional[Dict[str, Any]]:
        context: Dict[str, Any] = {}
        changes: Dict[str, Any] = {}
        new_rows: Dict[str, KeyedRows] = {}
        new_status: Dict[str, Dict[str, Any]] = {}
        for collection in self._collections:
            try:
                result = await collection.build(context)
            except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
                logger.warning("listing_push_build_failed", collection=collection.name,
                               error=str(exc), error_type=type(exc).__name__)
                continue
            rows, change = await asyncio.to_thread(self._keyed_diff, collection, result.rows)
            status = result.status_dict()
            if status != self._status.get(collection.name):
                change = dict(change or {})
                change["status"] = status
            if change:
                changes[collection.name] = change
            new_rows[collection.name] = rows
            new_status[collection.name] = status
        self._rows.update(new_rows)
        self._status.update(new_status)
        self._computed_at = time.monotonic()
        self.passes += 1
        if not changes:
            return None
        self.seq += 1
        frame = {"type": FRAME_TYPE, "stream": self.stream, "seq": self.seq, "changes": changes}
        self._publish(frame)
        return frame

    def _keyed_diff(self, collection: Collection, result_rows: List[Dict[str, Any]]):
        rows = keyed(result_rows, collection.key_of)
        return rows, diff(self._rows.get(collection.name), rows)

    async def snapshot(self, max_age: Optional[float] = None) -> Dict[str, Any]:
        limit = self.stale_seconds if max_age is None else max_age
        if self._computed_at is None:
            await self.run_pass()
        elif time.monotonic() - self._computed_at >= limit:
            if self._client_count() > 0:
                self.wake()
            else:
                await self.run_pass()
        return {
            "stream": self.stream,
            "seq": self.seq,
            "collections": {
                name: {"rows": [row for _, row in self._rows.get(name, [])],
                       **self._status.get(name, {"ok": False, "status": None, "detail": None, "meta": {}})}
                for name in (c.name for c in self._collections)
            },
        }

    def pace_after(self, took: float) -> float:
        return max(self.min_interval, took)


    async def run(self) -> None:
        logger.info("listing_push_started", backstop_seconds=self.backstop_seconds,
                    stream=self.stream)
        while True:
            wait = self.backstop_seconds
            if self._feed is not None and self._client_count() > 0:
                try:
                    if await self._feed():
                        wait = max(wait, EVENT_BACKSTOP_SECONDS)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("listing_push_feed_failed", error=str(exc), error_type=type(exc).__name__)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self._client_count() <= 0:
                continue
            started = time.monotonic()
            try:
                await self.run_pass()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("listing_push_pass_failed", error=str(exc),
                               error_type=type(exc).__name__)
            if self._after_pass is not None:
                try:
                    self._after_pass()
                except (OSError, RuntimeError, ValueError) as exc:
                    logger.warning("listing_push_after_pass_failed", error=str(exc),
                                   error_type=type(exc).__name__)
            self.last_pass_seconds = time.monotonic() - started
            await asyncio.sleep(self.pace_after(self.last_pass_seconds))

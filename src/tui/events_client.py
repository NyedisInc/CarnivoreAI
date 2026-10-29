
from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Awaitable, Callable, Optional

import structlog
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

from src.tui.api_client import ApiClient, AuthRequired, ServerUnavailable
from src.tui.listing_store import LIVENESS, ListingStore

logger = structlog.get_logger(__name__)

SUBPROTOCOL_MARKER = "cloude.jwt.v1"
EVENTS_PATH = "/ws/events"
LISTING_PATH = "/api/v1/sessions/listing"
POLL_SECONDS = 5.0
BACKOFF_BASE = 1.0
BACKOFF_CAP = 30.0
AUTH_REFUSED_STATUSES = (401, 403)


def backoff_delay(attempt: int, rng: Callable[[], float] = random.random) -> float:
    ceiling = min(BACKOFF_CAP, BACKOFF_BASE * (2 ** attempt))
    return ceiling * (0.5 + 0.5 * rng())


def events_url(base_url: str) -> str:
    return "ws" + base_url.rstrip("/")[len("http"):] + EVENTS_PATH


class EventsClient:

    def __init__(
        self,
        api: ApiClient,
        base_url: str,
        on_banner: Callable[[bool], None],
        on_auth_required: Callable[[], None],
        *,
        poll_seconds: float = POLL_SECONDS,
        rng: Callable[[], float] = random.random,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api = api
        self._url = events_url(base_url)
        self._on_banner = on_banner
        self._on_auth_required = on_auth_required
        self._poll_seconds = poll_seconds
        self._rng = rng
        self._sleep = sleep
        self.listing = ListingStore(self._fetch_snapshot)
        self.connected = False
        self.down = False
        self.hellos = 0
        self._auth_told = False
        self._topics: set[str] = set()
        self._topic_listeners: list[Callable[[list[str]], None]] = []
        self._poller: Optional[asyncio.Task[None]] = None
        self._task: Optional[asyncio.Task[None]] = None

    async def _fetch_snapshot(self) -> dict[str, Any]:
        resp = await self._api.request("GET", LISTING_PATH)
        if resp.status_code != 200:
            raise ServerUnavailable(str(resp.status_code))
        return resp.json()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self.run())

    async def stop(self) -> None:
        for task in (self._task, self._poller):
            if task is not None:
                task.cancel()
        for task in (self._task, self._poller):
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = self._poller = None

    def topic_pushed(self, topic: str) -> bool:
        family = topic.split(":", 1)[0]
        return self.connected and (topic in self._topics or family in self._topics)

    def on_topics(self, fn: Callable[[list[str]], None]) -> Callable[[], None]:
        self._topic_listeners.append(fn)
        return lambda: self._topic_listeners.remove(fn) if fn in self._topic_listeners else None

    async def run(self) -> None:
        attempt = 0
        refreshed_for: Optional[str] = None
        while True:
            try:
                await self._session()
                attempt, refreshed_for = 0, None
            except AuthRequired:
                self._auth_lost()
                return
            except InvalidStatus as exc:
                if exc.response.status_code in AUTH_REFUSED_STATUSES:
                    try:
                        refreshed_for = await self._reauth(refreshed_for)
                    except AuthRequired:
                        self._auth_lost()
                        return
                    except ServerUnavailable:
                        pass
                    else:
                        continue
            except (OSError, WebSocketException, ServerUnavailable, TimeoutError) as exc:
                logger.info("tui_events_down", error=type(exc).__name__)
            self._go_down()
            await self._sleep(backoff_delay(attempt, self._rng))
            attempt += 1

    async def _reauth(self, refreshed_for: Optional[str]) -> str:
        token = await self._api.access_token()
        if token == refreshed_for:
            await self._api.reject_access_token()
        return await self._api.refresh_access_token()

    async def _session(self) -> None:
        token = await self._api.access_token()
        async with connect(self._url, subprotocols=[SUBPROTOCOL_MARKER, token], open_timeout=10) as ws:
            async for raw in ws:
                self._dispatch(raw)

    def _dispatch(self, raw: Any) -> None:
        try:
            frame = json.loads(raw)
        except (TypeError, ValueError):
            return
        kind = frame.get("type") if isinstance(frame, dict) else None
        if kind == "events.hello":
            self._hello(frame)
        elif kind == "listing.delta":
            self.listing.frame(frame)
        elif kind == "resources.changed":
            topics = [t for t in frame.get("topics") or [] if isinstance(t, str)]
            self._tell_topics(topics)

    def _hello(self, frame: dict[str, Any]) -> None:
        self.connected = True
        self.hellos += 1
        self._topics = {t for t in frame.get("resource_topics") or [] if isinstance(t, str)}
        self._stop_poller()
        if self.down:
            self.down = False
            self._on_banner(False)
        self.listing.hello()
        self._tell_topics([LIVENESS])

    def _go_down(self) -> None:
        was_connected = self.connected
        self.connected = False
        self.listing.closed()
        if not self.down:
            self.down = True
            self._on_banner(True)
        if was_connected:
            self._tell_topics([LIVENESS])
        if self._poller is None or self._poller.done():
            self._poller = asyncio.ensure_future(self._poll_loop())

    def _auth_lost(self) -> None:
        if self._auth_told:
            return
        self._auth_told = True
        self.connected = False
        self.listing.closed()
        current = asyncio.current_task()
        if self._poller is not None and self._poller is not current:
            self._poller.cancel()
        self._on_auth_required()

    def _stop_poller(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
            self._poller = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.listing.poll()
            except AuthRequired:
                self._auth_lost()
                return
            except ServerUnavailable:
                pass
            await self._sleep(self._poll_seconds)

    def _tell_topics(self, topics: list[str]) -> None:
        for fn in list(self._topic_listeners):
            try:
                fn(topics)
            except Exception as exc:
                logger.warning("tui_topic_listener_failed", error=type(exc).__name__)

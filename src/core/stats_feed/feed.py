
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import closing
from functools import reduce
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import structlog

from src.core import resource_push
from src.core.db import DatastoreError, DatastoreUnreadableError
from src.core.resource_push import topics
from src.core.stats.store import StatsStore
from src.core.stats_feed import peers
from src.core.stats_feed import state as feed_state
from src.core.stats_feed.model import WINDOWS, Classes, fold, trailing_rate, window_start
from src.core.stats_feed.reader import Snapshot, read_probe, read_snapshot

logger = structlog.get_logger()

LEASE_S: float = 45.0
KEEPALIVE_S: float = 20.0
REFRESH_FLOOR_S: float = 1.0
WAKE_FRAMES = frozenset({"resources.changed", "stats.changed"})
LOCAL_KEY = "local"
LOCAL_LABEL = "this computer"

Lag = Tuple[Optional[int], Optional[int]]
Loaded = Tuple[Snapshot, feed_state.LocalState, Lag, bool]


class StatsFeed:

    def __init__(
        self,
        *,
        store_for: Callable[[], Optional[StatsStore]],
        state_dir: Path,
        db_path: Path,
        notify: Callable[[str, str, float], None] = resource_push.notify_coalesced,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._store_for = store_for
        self.state_dir = Path(state_dir)
        self.db_path = Path(db_path)
        self._notify = notify
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self.counters: Dict[str, int] = {"refreshes": 0, "full_reads": 0, "probes": 0, "lag_reads": 0,
                                         "wakes": 0, "unavailable": 0}
        self._lease_until = 0.0
        self._peer_lease_until = 0.0
        self._task: Optional["asyncio.Task[None]"] = None
        self._pull_task: Optional["asyncio.Task[None]"] = None
        self._ask_task: Optional["asyncio.Task[None]"] = None
        self._install_id: Optional[str] = None
        self.peer_book = peers.PeerBook()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._wake: Optional[asyncio.Event] = None
        self._lock = asyncio.Lock()
        self._snap: Optional[Snapshot] = None
        self._local: Optional[feed_state.LocalState] = None
        self._lag: Lag = (None, None)
        self._lag_at: Optional[float] = None
        self._as_of: Optional[float] = None
        self._generation = 0
        self._docs: Dict[str, Tuple[int, int, bytes]] = {}

    def local_word(self) -> Optional[str]:
        return self._local.word if self._local is not None else None


    def leased(self) -> bool:
        return self._clock() < max(self._lease_until, self._peer_lease_until)

    def owner_leased(self) -> bool:
        return self._clock() < self._lease_until

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._wake is None:
            self._wake = asyncio.Event()
        if not self.running:
            self._task = self._loop.create_task(self._run())

    def touch(self, *, pulled: bool = False) -> None:
        self._lease_until = self._clock() + LEASE_S
        self._start()
        if self._pull_task is None or self._pull_task.done():
            self._pull_task = self._loop.create_task(peers.pull(self, pulled=pulled))

    def touch_peer(self) -> None:
        self._peer_lease_until = self._clock() + LEASE_S
        self._start()

    def on_hub_frame(self, frame_type: Optional[str]) -> None:
        if frame_type in WAKE_FRAMES:
            self.mark_dirty(frame_type)

    def mark_dirty(self, reason: str) -> None:
        if not self.leased() or self._loop is None or self._wake is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._wake.set)
        except RuntimeError as exc:
            logger.debug("stats_feed_loop_closed", reason=reason, error=str(exc))
            return
        self.counters["wakes"] += 1

    async def _run(self) -> None:
        next_keepalive = self._clock() + KEEPALIVE_S
        while True:
            now = self._clock()
            until = max(self._lease_until, self._peer_lease_until)
            deadline = min(next_keepalive, until)
            if now >= until:
                break
            try:
                await asyncio.wait_for(self._wake.wait(), max(deadline - now, 0.0))
            except asyncio.TimeoutError:
                pass
            woke = self._wake.is_set()
            self._wake.clear()
            if not self.leased():
                break
            keepalive = self._clock() >= next_keepalive
            if not (woke or keepalive):
                continue
            changed = await self.refresh()
            if (changed or keepalive) and self.owner_leased():
                self._notify(topics.STATS_FEED, LOCAL_KEY, 1.0)
            if keepalive:
                next_keepalive = self._clock() + KEEPALIVE_S
            await self._sleep(REFRESH_FLOOR_S)
        logger.debug("stats_feed_idle")

    async def stop(self) -> None:
        self._lease_until = self._peer_lease_until = 0.0
        if self._pull_task is not None and not self._pull_task.done():
            self._pull_task.cancel()
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


    def _load(self, store: StatsStore, prev: Optional[Snapshot], lag: Lag, want_lag: bool) -> Loaded:
        revision, identity = read_probe(store)
        moved = prev is None or prev.revision != revision or prev.db_identity != identity
        snap = read_snapshot(store, self._wall()) if moved else prev
        if want_lag:
            lag = feed_state.read_lag(self.state_dir, self.db_path)
        return snap, feed_state.local_state(self.state_dir, snap, lag), lag, moved

    async def refresh(self) -> bool:
        async with self._lock:
            self.counters["refreshes"] += 1
            store = self._store_for()
            before = (self._snap.revision if self._snap else None, self._snap.db_identity if self._snap else None,
                      self._local.word if self._local else None)
            want_lag = self._lag_at is None or self._clock() - self._lag_at >= KEEPALIVE_S
            try:
                if store is None:
                    raise sqlite3.DatabaseError("the stats store is not open")
                snap, local, lag, moved = await asyncio.to_thread(self._load, store, self._snap, self._lag, want_lag)
            except (sqlite3.Error, OSError, DatastoreError, ValueError, TypeError, OverflowError) as exc:
                self.counters["unavailable"] += 1
                logger.warning("stats_feed_unavailable", error_type=type(exc).__name__, state_dir=str(self.state_dir))
                self._snap = self._local = None
                self._generation += 1
                return before != (None, None, None)
            self.counters["probes"] += 1
            self.counters["full_reads"] += int(moved)
            self.counters["lag_reads"] += int(want_lag)
            if want_lag:
                self._lag, self._lag_at = lag, self._clock()
            self._snap, self._local, self._as_of = snap, local, self._wall()
            after = (snap.revision, snap.db_identity, local.word)
            if after != before:
                self._generation += 1
            logger.debug("stats_feed_refresh", rev_moved=moved, word=local.word, rows=len(snap.minutes))
            return after != before


    def _measured(self, window: str, now: float) -> Tuple[list, Optional[Dict[str, float]], str]:
        spec = WINDOWS[window]
        snap, local = self._snap, self._local
        word = local.word if local else "unavailable"
        measuring = snap is not None and local is not None and word != "stats_off"
        held = word in feed_state.HELD
        bars = (fold(spec, now, snap.minutes, snap.hours, snap.gaps, (local.data_through or 0.0) if held else None)
                if measuring else [None] * spec.buckets)
        return bars, (trailing_rate(snap.minutes, now) if measuring and not held else None), word

    def _document(self, window: str, now: float) -> bytes:
        spec = WINDOWS[window]
        local = self._local
        own_bars, own_rate, word = self._measured(window, now)
        own_counted = [b for b in own_bars if b is not None]
        own_totals = _wire(reduce(Classes.plus, own_counted)) if own_counted else None
        merged = peers.overlay(self.peer_book, spec, now, self._clock(), own_bars, own_rate, word)
        counted = [b for b in merged.bars if b is not None]
        doc: Dict[str, Any] = {
            "v": 1, "rev": self._snap.revision if self._snap else None, "window": window, "bucket_seconds": spec.bucket_s,
            "start": window_start(spec, now), "now": round(now, 1),
            "state": merged.state,
            "in": [None if b is None else b.tokens_in for b in merged.bars],
            "out": [None if b is None else b.out for b in merged.bars],
            "totals": _wire(reduce(Classes.plus, counted)) if counted else None, "rate": merged.rate,
            "sources": [{"host_key": LOCAL_KEY, "label": LOCAL_LABEL, "state": word,
                         "data_through": local.data_through if local else None, "as_of": self._as_of,
                         "totals": own_totals}, *merged.sources],
        }
        return json.dumps(doc, separators=(",", ":")).encode()

    def _served(self, window: str) -> bytes:
        now = self._wall()
        hit = self._docs.get(window)
        if hit is not None and hit[0] == self._generation and hit[1] == int(now):
            return hit[2]
        body = self._document(window, now)
        self._docs[window] = (self._generation, int(now), body)
        return body

    async def body(self, window: str, *, lease: bool = True) -> bytes:
        maintained = self.leased() and self._snap is not None
        ask_peers = not self.owner_leased() or self._ask_inflight()
        asking = self._ask_peers_once() if ask_peers else None
        if lease:
            self.touch(pulled=ask_peers)
        if not maintained:
            await self.refresh()
        if asking is not None:
            await asyncio.shield(asking)
        return self._served(window)

    def _ask_inflight(self) -> bool:
        return self._ask_task is not None and not self._ask_task.done()

    def _ask_peers_once(self) -> Optional["asyncio.Future[None]"]:
        if not self._ask_inflight():
            asked = self.peer_book.asked_mono
            if asked is not None and self._clock() - asked < peers.PULL_S:
                return None
            self._ask_task = asyncio.get_running_loop().create_task(self._ask_and_bump())
        return self._ask_task

    async def _ask_and_bump(self) -> None:
        await peers.pull_once(self)
        self._generation += 1

    async def local_answer(self) -> Dict[str, Any]:
        if not (self.leased() and self._snap is not None):
            await self.refresh()
        now, snap, local = self._wall(), self._snap, self._local
        word = local.word if local else "unavailable"
        windows: Optional[Dict[str, list]] = None
        rate = None
        if snap is not None and word not in ("stats_off", "unavailable"):
            windows = {}
            for name, spec in WINDOWS.items():
                bars, rate_now, _ = self._measured(name, now)
                start = window_start(spec, now)
                windows[name] = [[start + i * spec.bucket_s, *b] for i, b in enumerate(bars) if b is not None and any(b)]
                rate = rate_now
        return {"v": peers.WIRE_VERSION, "install_id": await self._own_install_id(), "rev": snap.revision if snap else 0,
                "now": round(now, 1), "state": word, "data_through": local.data_through if local else None,
                "rate": rate, "windows": windows, "gaps": [list(g) for g in snap.gaps[-peers.MAX_GAPS:]] if snap else []}

    async def _own_install_id(self) -> str:
        if self._install_id is None:
            from src.api import peer_auth

            def read() -> str:
                with closing(peer_auth.open_db()) as conn:
                    return peer_auth.read_install_id(conn) or ""
            try:
                self._install_id = await asyncio.to_thread(read)
            except (sqlite3.Error, OSError, DatastoreUnreadableError) as exc:
                logger.warning("stats_feed_install_id_unreadable", error_type=type(exc).__name__)
                return ""
        return self._install_id

    def peers_changed(self) -> None:
        self._generation += 1
        self._notify(topics.STATS_FEED, LOCAL_KEY, 1.0)

    def diagnostics(self) -> Dict[str, Any]:
        return {**self.counters, "leased": self.leased(), "running": self.running}


def _wire(counts: Classes) -> Dict[str, int]:
    return {"fresh": counts.fresh, "cache_write": counts.cache_write, "cache_read": counts.cache_read, "out": counts.out}


def install(state: Any) -> StatsFeed:
    feed = getattr(state, "stats_feed", None)
    if feed is None:
        from src.config import settings
        from src.core.db import db_path_for

        state_dir = settings.get_state_dir()
        feed = StatsFeed(store_for=lambda: getattr(state, "stats_store", None), state_dir=state_dir,
                         db_path=db_path_for(state_dir))
        state.stats_feed = feed
        hub = getattr(state, "event_hub", None)
        if hub is not None:
            hub.add_listener(feed.on_hub_frame)
    return feed

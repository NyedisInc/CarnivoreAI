
from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Mapping, Optional, Sequence, Set, Tuple

import structlog

from src.core.pipeline import contract as C
from src.core.pipeline import plugin_db
from src.core.pipeline.log import log_error

logger = structlog.get_logger()

THREAD_NAME: str = "pipeline-lifecycle"
RETRY_DELAYS: Sequence[float] = (1.0, 2.0, 5.0, 15.0, 60.0)
MAX_QUEUED: int = 256
MAX_ANNOUNCE_QUEUED: int = 256
ANNOUNCE_THREAD_NAME: str = "pipeline-lifecycle-announce"

Writer = Callable[..., str]
Resolve = Callable[[], Optional[Tuple[str, Mapping[str, Any]]]]
UNRESOLVED: str = "unresolved"


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


@dataclass
class _Item:

    kind: str
    conversation_id: str
    at_ts: float
    payload: Mapping[str, Any]
    future: "Future[str]"
    attempts: int = 0
    due: float = 0.0
    result: Optional[str] = None
    announced: bool = False
    resolve: Optional[Resolve] = None
    plugins_done: Set[str] = field(default_factory=set)


class _Announcer:

    def __init__(self, deliver: Callable[["_Item"], None], limit: Optional[int] = None) -> None:
        self._deliver = deliver
        self._limit = max(1, MAX_ANNOUNCE_QUEUED if limit is None else limit)
        self._lock = threading.Lock()
        self._events: Deque["_Item"] = deque()
        self._thread: Optional[threading.Thread] = None

    def put(self, item: "_Item") -> None:
        dropped: Optional["_Item"] = None
        with self._lock:
            if len(self._events) >= self._limit:
                dropped = self._events.popleft()
            self._events.append(item)
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name=ANNOUNCE_THREAD_NAME, daemon=True)
                self._thread.start()
        if dropped is not None:
            log_error("pipeline_lifecycle_announce_dropped", plugin="lifecycle", error="announce queue full",
                      kind=dropped.kind)

    def pending(self) -> int:
        with self._lock:
            return len(self._events)

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._events:
                    self._thread = None
                    return
                item = self._events.popleft()
            self._deliver(item)


class Lifecycle:

    def __init__(self, db_path: Optional[Path], *, state_dir: Optional[Path] = None,
                 plugins: Sequence[C.Plugin] = (), writer: Optional[Writer] = None,
                 clock: Callable[[], float] = time.monotonic, retry_delays: Sequence[float] = RETRY_DELAYS) -> None:
        self._db_path = db_path
        self._state_dir = Path(state_dir) if state_dir is not None else None
        self._hooked = tuple(p for p in plugins if p.on_lifecycle is not None)
        self._writer = writer
        self._clock = clock
        self._delays = tuple(retry_delays) or (1.0,)
        self._cond = threading.Condition()
        self._items: Deque[_Item] = deque()
        self._thread: Optional[threading.Thread] = None
        self._announcer = _Announcer(self._announce)

    def write_milestone(self, kind: str, conversation_id: str, at_ts: float,
                        payload: Optional[Mapping[str, Any]] = None,
                        resolve: Optional[Resolve] = None) -> "Future[str]":
        item = _Item(kind, conversation_id, float(at_ts), dict(payload or {}), Future(), resolve=resolve)
        with self._cond:
            if len(self._items) >= MAX_QUEUED:
                dropped = self._items.popleft()
                dropped.future.set_result("dropped")
                log_error("pipeline_lifecycle_dropped", plugin="lifecycle", error="retry list full",
                          kind=dropped.kind)
            self._items.append(item)
            if self._thread is None:
                self._thread = threading.Thread(target=self._drain, name=THREAD_NAME, daemon=True)
                self._thread.start()
            self._cond.notify()
        return item.future

    def alive(self) -> bool:
        with self._cond:
            return self._thread is not None and self._thread.is_alive()

    def pending(self) -> int:
        with self._cond:
            return len(self._items)

    def _drain(self) -> None:
        while True:
            with self._cond:
                now = self._clock()
                item = next((i for i in self._items if i.due <= now), None)
                if item is None:
                    if not self._items:
                        self._thread = None
                        return
                    self._cond.wait(max(0.0, min(i.due for i in self._items) - now))
                    continue
                self._items.remove(item)
            self._attempt(item)

    def _attempt(self, item: _Item) -> None:
        try:
            if item.resolve is not None:
                found = item.resolve()
                if found is None:
                    item.future.set_result(UNRESOLVED)
                    return
                item.conversation_id, item.payload = found[0], {**item.payload, **found[1]}
                item.resolve = None
            if item.result is None:
                item.result = self._write(item)
            if not item.announced:
                item.announced = True
                self._announcer.put(item)
            for plugin in self._hooked:
                if plugin.id not in item.plugins_done:
                    self._call_hook(plugin, item)
                    item.plugins_done.add(plugin.id)
        except Exception as exc:  # noqa: BLE001
            item.attempts += 1
            delay = self._delays[min(item.attempts - 1, len(self._delays) - 1)]
            log_error("pipeline_lifecycle_failed", plugin="lifecycle", error=exc, kind=item.kind)
            with self._cond:
                item.due = self._clock() + delay
                self._items.append(item)
                self._cond.notify()
            return
        item.future.set_result(item.result or "")

    def _write(self, item: _Item) -> str:
        if self._db_path is None:
            return "off"
        writer = self._writer
        if writer is None:
            from src.core.lineage.events import write_capture_event as writer
        return writer(self._db_path, item.kind, item.conversation_id, item.payload.get("session_uuid"),
                      child_conversation_id=item.payload.get("child_conversation_id"), at_ts=iso(item.at_ts))

    @staticmethod
    def _announce(item: _Item) -> None:
        try:
            from src.cplugs.sdk import save_triggers  # noqa: PLC0415

            if not save_triggers.is_lifecycle(item.kind):
                return
            save_triggers.announce(save_triggers.LifecycleSave(
                event=item.kind, conversation_id=item.conversation_id, session_uuid=item.payload.get("session_uuid"),
                family=item.payload.get("family") or "claude", facts=dict(item.payload.get("facts") or {})))
        except Exception as exc:  # noqa: BLE001
            log_error("pipeline_lifecycle_announce_failed", plugin="lifecycle", error=exc, kind=item.kind)

    def _call_hook(self, plugin: C.Plugin, item: _Item) -> None:
        from src.core.db import transaction

        if self._state_dir is None:
            return
        with plugin_db.lock_for(plugin.id):
            conn = plugin_db.open_db(self._state_dir, plugin)
            try:
                with transaction(conn):
                    plugin.on_lifecycle(conn, item.kind, item.conversation_id, item.at_ts, item.payload)
            finally:
                conn.close()

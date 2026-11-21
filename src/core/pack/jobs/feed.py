
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Callable, Dict, List, Optional

import structlog

from src.core.pack.jobs import view
from src.core.pack.jobs.store import JobStore
from src.models.websocket import WSMessageType

log = structlog.get_logger(__name__)

LabelFn = Callable[[str], str]


class JobsFeed:

    def __init__(self, hub: Any, store: JobStore, *, coalesce_s: float = 2.0, label_of: Optional[LabelFn] = None,
                 loop: Optional[asyncio.AbstractEventLoop] = None, on_caller: Optional[Callable[[str], None]] = None) -> None:
        self._hub, self._store, self._window = hub, store, coalesce_s
        self._label_of = label_of
        self._on_caller = on_caller
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
        self._loop = loop
        self._seq = 0
        self._timers: Dict[str, asyncio.TimerHandle] = {}

    def seq(self) -> int:
        return self._seq

    def changed(self, job_id: str, state_changed: bool) -> None:
        if job_id.startswith(view.WARM_PREFIX):
            return
        self._on_loop(self._changed, job_id, state_changed)

    def removed(self, ids: List[str]) -> None:
        ids = [i for i in ids if not i.startswith(view.WARM_PREFIX)]
        if ids:
            self._on_loop(self._removed, ids)

    def _on_loop(self, fn: Callable[..., None], *args: Any) -> None:
        if self._loop is None:
            fn(*args)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            fn(*args)
            return
        try:
            self._loop.call_soon_threadsafe(fn, *args)
        except RuntimeError as exc:
            log.debug("pack_jobs_feed_loop_closed", error=str(exc))

    def _changed(self, job_id: str, state_changed: bool) -> None:
        if state_changed or self._loop is None:
            timer = self._timers.pop(job_id, None)
            if timer is not None:
                timer.cancel()
            self._send_job(job_id)
        elif job_id not in self._timers:
            self._timers[job_id] = self._loop.call_later(self._window, self._timer_fired, job_id)

    def _timer_fired(self, job_id: str) -> None:
        self._timers.pop(job_id, None)
        self._send_job(job_id)

    def _removed(self, ids: List[str]) -> None:
        for job_id in ids:
            timer = self._timers.pop(job_id, None)
            if timer is not None:
                timer.cancel()
        self._publish({"removed": ids})

    def _send_job(self, job_id: str) -> None:
        try:
            rec = self._store.get_job(job_id)
            host = None if rec is not None else self._store.host_get(job_id)
        except sqlite3.Error as exc:
            log.warning("pack_jobs_feed_read_failed", error=type(exc).__name__)
            return
        if rec is not None:
            self._publish({"job": view.job_view(rec)})
            if rec.caller_session and self._on_caller is not None:
                self._on_caller(rec.caller_session)
            return
        if host is None:
            return
        label = (self._label_of(host.caller_install) if self._label_of
                 else view.host_labels(self._store.state_dir, [host.caller_install]).get(host.caller_install))
        self._publish({"job": view.host_view(host, label)})

    def _publish(self, body: Dict[str, Any]) -> None:
        self._seq += 1
        frame = {"type": WSMessageType.PACK_JOBS_DELTA.value, "seq": self._seq, **body}
        try:
            self._hub.publish(frame)
        except (TypeError, ValueError, RuntimeError) as exc:
            log.warning("pack_jobs_feed_publish_failed", error=type(exc).__name__)

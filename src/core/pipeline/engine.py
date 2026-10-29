
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.pipeline import contract as C
from src.core.pipeline import activity, plugin_db, recent, registry, scan, status
from src.core.pipeline.deliver import (Delivery, FileTarget, PluginRun, SKIP_BUDGET, SKIP_GONE, SKIP_ICLOUD,
                                       SKIP_TIMEOUT, SKIP_UNREADABLE, deliver_file, deliver_file_removed, deliver_removed)
from src.core.pipeline.lifecycle import Lifecycle
from src.core.pipeline.lineage_edge import lineage_of
from src.core.pipeline.log import log_error
from src.core.pipeline.observe import (KIND_FILE_REMOVED, TRIGGER_LIVE, DirtySet, Entry, Observer, Waiting)

logger = structlog.get_logger()

THREAD_WORKER: str = "pipeline-worker"
THREAD_SCAN: str = "pipeline-scan"
BATCH_KEYS: int = 64
BATCH_WALL_SECONDS: float = 20.0
RUN_HELD: str = "held"
WORKER_ERROR_PAUSE_SECONDS: float = 5.0
PARK_WORKER_ERROR: str = "worker_error"
PARK_REASONS = frozenset({SKIP_TIMEOUT, SKIP_ICLOUD, SKIP_UNREADABLE})
PUSH_INTERVAL_SECONDS: float = 2.0
PUSH_KEY: str = "engine"
Wait = Callable[[threading.Event, Optional[float]], bool]


def _real_wait(event: threading.Event, timeout: Optional[float]) -> bool:
    return event.wait(timeout)


def push_status() -> None:
    from src.core import resource_push
    from src.core.resource_push import topics

    resource_push.notify_coalesced(topics.PIPELINE, PUSH_KEY, PUSH_INTERVAL_SECONDS)


class Engine:

    def __init__(self, state_dir: Path, *, db_path: Optional[Path] = None,
                 plugins: Optional[Sequence[C.Plugin]] = None, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time, wait: Wait = _real_wait,
                 refresh_fn: Optional[Callable[[], Any]] = None,
                 scan_interval: float = scan.SCAN_INTERVAL_SECONDS,
                 lineage_fn: Optional[Callable[[str], Optional[C.Lineage]]] = None,
                 lifecycle_writer: Optional[Callable[..., str]] = None,
                 recent_runs: Optional[recent.RecentRuns] = None,
                 notify: Callable[[], None] = push_status) -> None:
        self.state_dir = Path(state_dir)
        self.db_path = Path(db_path) if db_path is not None else None
        self.plugins = tuple(registry.plugins() if plugins is None else registry.plugins(plugins))
        self._clock = clock
        self._wall = wall
        self._wait = wait
        self._scan_interval = scan_interval
        self._lineage_fn = lineage_fn if lineage_fn is not None else (
            (lambda conv: lineage_of(self.db_path, conv)) if self.db_path is not None else (lambda conv: None))
        self.dirty = DirtySet(clock)
        self.scanner = scan.Scanner(self.state_dir, self.db_path, self.plugins, self.mark_dirty, self.mark_removed,
                                    refresh_fn=refresh_fn, wall=wall, mark_file_removed=self.mark_file_removed)
        self.lifecycle = Lifecycle(self.db_path, state_dir=self.state_dir, plugins=self.plugins,
                                   writer=lifecycle_writer)
        self.observer = Observer(self.mark_dirty)
        self.recent = recent_runs if recent_runs is not None else recent.RecentRuns(
            recent.db_resolver(self.db_path), wall=wall, clock=clock)
        self._notify = notify
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._deliver_lock = threading.Lock()
        self._threads: Dict[str, threading.Thread] = {}
        self._start_lock = threading.Lock()
        self._paused: set = set()
        self._rebuilding: Dict[str, float] = {}
        self._rebuild_started: Dict[str, List[float]] = {}
        self._rebuild_busy = 0
        self._bulk_rest_until = 0.0
        self._rebuild_lock = threading.Lock()
        self._in_flight: Dict[Any, Entry] = {}
        self._current: Optional[activity.InFlight] = None
        self._batch_rest: Tuple[Waiting, ...] = ()
        self._activity_lock = threading.Lock()
        self._rescan_lock = threading.Lock()
        self._rescan_running = False
        self._rescan_again = False
        self._last_progress = clock()
        self._last_delivery_wall: Optional[float] = None
        self._tallies: Dict[str, status.PluginTally] = {p.id: status.PluginTally() for p in self.plugins}
        self.wakes = 0
        self.scan_ticks = 0

    def mark_dirty(self, target: FileTarget, trigger: str = TRIGGER_LIVE) -> bool:
        created = self.dirty.mark_file(target, trigger)
        if created:
            self._wake.set()
        return created

    def mark_removed(self, conversation_id: str, family: str, trigger: str = TRIGGER_LIVE) -> bool:
        created = self.dirty.mark_removed(conversation_id, family, trigger)
        if created:
            self._wake.set()
        return created

    def mark_file_removed(self, target: FileTarget, trigger: str = TRIGGER_LIVE) -> bool:
        created = self.dirty.mark_file_removed(target, trigger)
        if created:
            self._wake.set()
        return created

    def rescan(self) -> None:
        with self._rescan_lock:
            if self._rescan_running:
                self._rescan_again = True
                return
            self._rescan_running = True

        def work() -> None:
            while True:
                try:
                    self.scanner.mark_pass()
                    self.signal_caught_up()
                    self._push()
                except Exception as exc:  # noqa: BLE001
                    log_error("pipeline_rescan_failed", plugin="engine", error=exc)
                with self._rescan_lock:
                    again, self._rescan_again = self._rescan_again, False
                    if not again:
                        self._rescan_running = False
                        return

        threading.Thread(target=work, name="pipeline-rescan", daemon=True).start()

    def write_milestone(self, kind: str, conversation_id: str, at_ts: float, payload: Optional[Dict[str, Any]] = None,
                        resolve: Optional[Callable[[], Any]] = None):
        return self.lifecycle.write_milestone(kind, conversation_id, at_ts, payload, resolve)

    def step(self) -> Optional[float]:
        resting = self._clock() < self._bulk_rest_until
        entries = self.dirty.take(BATCH_KEYS, bulk=not resting)
        changed = bool(entries)
        if entries:
            self.recent.prepare(e.conversation_id for e in entries if e.trigger == TRIGGER_LIVE)
            started = self._clock()
            self._deliver_batch(entries)
            if not any(e.live for e in entries):
                self._bulk_rest_until = self._clock() + min(C.BULK_REST_MAX_SECONDS, C.BULK_REST_RATIO * (self._clock() - started))
        if self._rebuilding and not self._rebuild_busy and not self.dirty.size() and not self._in_flight:
            self._rebuilding.clear()
            changed = True
        if entries:
            self.signal_caught_up()
        if changed:
            self._push()
        if self._clock() < self._bulk_rest_until:
            rest = self._bulk_rest_until - self._clock()
            if self.dirty.size() == 0:
                return None
            live = self.dirty.next_delay(bulk=False)
            return rest if live is None else min(rest, live)
        return self.dirty.next_delay()

    def run_worker(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                delay = self.step()
            except Exception as exc:  # noqa: BLE001
                log_error("pipeline_worker_failed", plugin="engine", error=exc)
                delay = WORKER_ERROR_PAUSE_SECONDS
            if delay is not None and delay <= 0:
                continue
            self._wait(self._wake, delay)
            self.wakes += 1

    def run_scan(self) -> None:
        while not self._stop.is_set():
            self.scanner.run_once()
            self.scan_ticks += 1
            self.signal_caught_up()
            self._push()
            self._wait(self._stop, self._scan_interval)

    def signal_caught_up(self) -> bool:
        with self._deliver_lock:
            last = self.scanner.last
            if last is None or last.get("status") != "ok" or self._rebuild_busy or self._in_flight:
                return False
            view = self.dirty.view()
            if view.pending > view.parked:
                return False
            for plugin in self.plugins:
                if plugin.on_caught_up is None or plugin.id in self._paused:
                    continue
                try:
                    with plugin_db.lock_for(plugin.id):
                        conn = plugin_db.pooled_db(self.state_dir, plugin)
                        plugin.on_caught_up(conn)
                except Exception as exc:  # noqa: BLE001
                    if isinstance(exc, (sqlite3.Error, plugin_db.PluginUnavailable)):
                        plugin_db.discard_pooled(self.state_dir, plugin)
                    log_error("pipeline_caught_up_failed", plugin=plugin.id, error=exc)
        return True

    def _push(self) -> None:
        try:
            self._notify()
        except Exception as exc:  # noqa: BLE001
            log_error("pipeline_push_failed", plugin="engine", error=exc)

    def _deliver_batch(self, entries: List[Entry]) -> None:
        with self._deliver_lock:
            runs = [PluginRun(p) for p in self.plugins if p.id not in self._paused]
            delivery = Delivery(self.state_dir, runs, TRIGGER_LIVE, None, clock=self._wall, timer=self._clock)
            self._in_flight = {e.key: e for e in entries}
            copies = self.dirty.waiting_copies(entries)
            self._set_batch_rest(copies)
            started = self._clock()
            try:
                bulk_only = not any(e.live for e in entries)
                for index, entry in enumerate(entries):
                    if index and (self._clock() - started > BATCH_WALL_SECONDS
                                  or (bulk_only and self.dirty.next_delay(bulk=False) == 0.0)):
                        self._set_batch_rest(())
                        for rest in entries[index:]:
                            self._in_flight.pop(rest.key, None)
                            self.dirty.settle(rest, requeue=True)
                        break
                    self._set_batch_rest(copies[index + 1:])
                    try:
                        self._deliver_entry(delivery, entry)
                    finally:
                        self._set_current(None)
                    self._in_flight.pop(entry.key, None)
            finally:
                self._set_batch_rest(())
                for entry in list(self._in_flight.values()):
                    self.dirty.settle(entry, file_error=PARK_WORKER_ERROR)
                self._in_flight = {}
                delivery.close_reads()

    def _set_batch_rest(self, rest: Tuple[Waiting, ...]) -> None:
        with self._activity_lock:
            self._batch_rest = rest

    def _set_current(self, current: Optional[activity.InFlight]) -> None:
        with self._activity_lock:
            self._current = current
        if current is not None:
            self._push()

    def _deliver_entry(self, delivery: Delivery, entry: Entry) -> None:
        held = self.dirty.held(entry.key)
        for run in delivery.runs:
            run.failed = RUN_HELD if run.plugin.id in held else None
        active = [r for r in delivery.runs if r.failed is None]
        if not active:
            self.dirty.settle(entry)
            return
        self._set_current(activity.InFlight(entry.conversation_id, entry.family, entry.trigger,
                                            tuple(r.plugin.id for r in active), self._clock()))
        moved_before = sum(r.events + r.resets + r.removed for r in delivery.runs)
        before = {id(r): (r.busy_seconds, r.events + r.resets + r.removed) for r in active}
        budget_before = delivery.skipped_files.get(SKIP_BUDGET, 0)
        delivery.trigger = entry.trigger
        reason: Optional[str] = None
        try:
            if entry.target is None:
                delivery.lineage = None
                deliver_removed(delivery, entry.conversation_id)
            elif entry.key[0] == KIND_FILE_REMOVED:
                delivery.lineage = None
                deliver_file_removed(delivery, entry.target)
            else:
                delivery.lineage = self._lineage_fn(entry.conversation_id)
                reason = deliver_file(delivery, replace(entry.target, rewritten=entry.rewritten))
        except Exception as exc:  # noqa: BLE001
            log_error("pipeline_deliver_failed", plugin="engine", error=exc)
            reason = SKIP_UNREADABLE
        failures = {r.plugin.id: r.failed for r in active if r.failed}
        file_error = str(reason) if reason in PARK_REASONS else None
        out_of_budget = reason == SKIP_BUDGET or delivery.skipped_files.get(SKIP_BUDGET, 0) > budget_before
        delay = self.dirty.settle(
            entry, ok=[] if file_error else [r.plugin.id for r in active if not r.failed], failures=failures,
            file_error=file_error, file_ok=file_error is None, requeue=out_of_budget and file_error is None)
        if file_error:
            log_error("pipeline_file_parked", plugin="engine", error=file_error, retry_in_s=delay, path=entry.key[1])
        moved = sum(r.events + r.resets + r.removed for r in delivery.runs) > moved_before
        if moved or (not failures and not file_error and reason != SKIP_GONE):
            self._last_progress = self._clock()
        if moved:
            self._last_delivery_wall = self._wall()
            logger.debug("pipeline_delivered", key=entry.key[1], plugins=[r.plugin.id for r in active])
        if reason != SKIP_GONE:
            try:
                self._record_runs(entry, active, before, file_error)
            except Exception as exc:  # noqa: BLE001
                log_error("pipeline_recent_record_failed", plugin="engine", error=exc)

    def _record_runs(self, entry: Entry, active: List[PluginRun], before: Dict[int, tuple],
                     file_error: Optional[str]) -> None:
        area = None if entry.trigger == TRIGGER_LIVE else recent.MACHINE
        for run in active:
            busy, moved = before[id(run)]
            delta = run.events + run.resets + run.removed - moved
            if file_error:
                if entry.target is None or not run.plugin.reads(entry.family, entry.target.file_kind):
                    continue
                outcome, error = recent.OUTCOME_PARKED, file_error
            elif run.failed:
                outcome, error = recent.OUTCOME_FAILED, run.failed
            elif delta > 0:
                outcome, error = recent.OUTCOME_OK, None
            else:
                continue
            tally = self._tallies[run.plugin.id]
            tally.runs += 1
            if outcome == recent.OUTCOME_OK:
                tally.last_delivery_at = self._wall()
            self.recent.record(plugin_id=run.plugin.id, conversation_id=entry.conversation_id, family=entry.family,
                               trigger=entry.trigger, duration_s=run.busy_seconds - busy, outcome=outcome,
                               events=delta, error=error, area=area)

    def start(self) -> None:
        with self._start_lock:
            if self._threads:
                return
            self._stop.clear()
            for name, body in ((THREAD_WORKER, self.run_worker), (THREAD_SCAN, self.run_scan)):
                thread = threading.Thread(target=body, name=name, daemon=True)
                self._threads[name] = thread
                thread.start()
            logger.info("pipeline_started", plugins=[p.id for p in self.plugins], threads=sorted(self._threads),
                        scan_interval_s=self._scan_interval)
        self._push()

    def stop(self, timeout: float = 10.0) -> None:
        with self._start_lock:
            self._stop.set()
            self._wake.set()
            for thread in self._threads.values():
                thread.join(timeout)
            self._threads = {}
        self._push()

    def pause(self, plugin_id: str) -> None:
        self._paused.add(plugin_id)
        with self._deliver_lock:
            pass
        self._push()

    def resume(self, plugin_id: str) -> None:
        self._paused.discard(plugin_id)
        self._wake.set()
        self._push()

    def begin_rebuild(self, plugin_id: str) -> None:
        with self._rebuild_lock:
            self._rebuild_busy += 1
            self._rebuilding[plugin_id] = self._wall()
        self.pause(plugin_id)
        with self._rebuild_lock:
            self._rebuild_started.setdefault(plugin_id, []).append(self._clock())

    def end_rebuild(self, plugin_id: str, error: Optional[str] = None) -> None:
        with self._rebuild_lock:
            self._rebuild_busy -= 1
            starts = self._rebuild_started.get(plugin_id) or []
            started = starts.pop(0) if starts else None
            if not starts:
                self._rebuild_started.pop(plugin_id, None)
        took = 0.0 if started is None else self._clock() - started
        try:
            self.recent.record_rebuild(plugin_id=plugin_id, duration_s=took, error=error,
                                       outcome=recent.OUTCOME_FAILED if error else recent.OUTCOME_OK)
        except Exception as exc:  # noqa: BLE001
            log_error("pipeline_recent_record_failed", plugin="engine", error=exc)
        finally:
            self.resume(plugin_id)

    def rebuild_plugin(self, plugin_id: str) -> Dict[str, Any]:
        from src.core.pipeline.rebuild import rebuild_plugin

        return rebuild_plugin(self, plugin_id)

    def status(self) -> Dict[str, Any]:
        with self._activity_lock:
            current = self._current
            batch_rest = self._batch_rest
        rebuilding = dict(self._rebuilding)
        head = list(batch_rest[:activity.QUEUE_LIMIT])
        waiting, pending = self.dirty.queue(activity.QUEUE_LIMIT - len(head))
        waiting, pending = head + waiting, pending + len(batch_rest)
        now, wall = self._clock(), self._wall()
        lookup = self.recent.cached_lookup
        snapshot = status.Snapshot(
            now=now, wall=wall, view=self.dirty.view(), in_flight=len(self._in_flight),
            last_progress=self._last_progress, last_delivery_wall=self._last_delivery_wall, plugins=self.plugins,
            rebuilding=tuple(rebuilding), scan=self.scanner.last, recent=tuple(self.recent.rows()),
            tallies={pid: (t.last_delivery_at, t.runs) for pid, t in self._tallies.items()},
            threads={"worker": self._alive(THREAD_WORKER), "scan": self._alive(THREAD_SCAN),
                     "lifecycle": self.lifecycle.alive()},
            running=tuple(activity.running_rows(current, rebuilding, now=now, wall=wall, lookup=lookup)),
            queue=activity.queue_rows(waiting, pending, now=now, wall=wall, lookup=lookup))
        return status.build(snapshot)

    def _alive(self, name: str) -> bool:
        thread = self._threads.get(name)
        return thread is not None and thread.is_alive()

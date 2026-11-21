
from __future__ import annotations

import asyncio
import dataclasses
import os
import platform
import sqlite3
import time
from contextlib import closing
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.db_reuse.kept_read import hot_read
from src.core.pack.jobs import boot as jobs_boot, metrics as jobs_metrics, miss_count, paths as jobs_paths, place as jobs_place, policy as jobs_policy, runner as jobs_runner
from src.core.pack.jobs.types import TERMINAL, JobError
from src.core.pack.load import process_tree
from src.core.pack.placement import queue as spawn_queue, rule as placement_rule, workload as placement_workload
from src.core.pack.reserve import attached, holds as holds_mod, pressure, session_demote, throttle as throttle_mod
from src.core.swarm import switch as swarm_switch

logger = structlog.get_logger()


async def drain(app_state: Any, open_db: Callable[[], sqlite3.Connection]) -> int:
    from src.core.swarm import body, spawn, store

    def load():
        with closing(open_db()) as conn:
            expired = spawn_queue.expire_old(conn)
            return expired, spawn_queue.list_queue(conn)

    expired, waiting = await asyncio.to_thread(load)
    for row in expired:
        parent_id = row["request"].get("parent_id")
        parent = await body.run_db(lambda c, pid=parent_id: store.get_agent(c, pid)) if parent_id else None
        if parent is not None:
            await body._card(parent, "spawn dropped", f"{row['request'].get('args', {}).get('job', 'a spawn')} waited an hour for a "
                             "computer with room and was dropped.", f"spawn_queue_expired:{row['id']}")
    started = 0
    for row in waiting:
        request = row["request"]

        def note(state: str, reason: str, queue_id: int = row["id"]) -> None:
            with closing(open_db()) as conn:
                (spawn_queue.mark_placed if state == "placed" else spawn_queue.note_attempt)(conn, queue_id, reason)

        try:
            parent = await body.run_db(lambda c: store.get_agent(c, request["parent_id"]))
            if parent is None or parent["torn_down_at"] is not None:
                await asyncio.to_thread(_cancel, open_db, row["id"], "its parent agent is gone")
                continue
            plan = dataclasses.replace(await spawn.prepare_for(parent, request["args"]), queue_id=row["id"])
            await spawn.run_for(app_state, plan)
            await asyncio.to_thread(note, "placed", "started from the queue")
            started += 1
        except spawn.SpawnQueued as exc:
            await asyncio.to_thread(note, "queued", str(exc))
        except spawn.SpawnRefused as exc:
            await asyncio.to_thread(_cancel, open_db, row["id"], f"refused: {exc}"[:500])
        except (sqlite3.Error, KeyError, TypeError, OSError) as exc:
            logger.warning("pack_queue_retry_failed", queue_id=row["id"], error=type(exc).__name__)
    return started


def _count_waiting(open_db: Callable[[], sqlite3.Connection]) -> int:
    return hot_read(open_db, ("spawn_queue_waiting",), spawn_queue.count_queued)


def _cancel(open_db: Callable[[], sqlite3.Connection], queue_id: int, reason: str) -> None:
    with closing(open_db()) as conn:
        spawn_queue.cancel(conn, queue_id)
        with conn:
            conn.execute("UPDATE pack_spawn_queue SET last_reason = ? WHERE id = ?", (reason, queue_id))


class MetricsBeat:

    FLUSH_SECONDS = 60.0

    def __init__(self, wired: Any, gauge: pressure.Gauge, *, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time) -> None:
        self._wired, self._gauge, self._clock, self._wall = wired, gauge, clock, wall
        self._counter: Optional[miss_count.MissCounter] = None
        self._flushed = float("-inf")

    def _marked_sessions(self, store: Any) -> Dict[str, Tuple[str, str]]:
        uids = store.marked_projects()
        if not uids:
            return {}
        marks = ",".join("?" for _ in uids)
        with closing(self._wired.open_db()) as conn:
            rows = conn.execute("SELECT s.tmux_name, p.uid, s.session_uuid FROM sessions s JOIN projects p ON p.id = s.project_id "
                                f"WHERE p.uid IN ({marks}) AND s.tmux_name IS NOT NULL", uids).fetchall()
        return {str(n): (str(u), str(s)) for n, u, s in rows}

    def _recent_delegate(self, store: Any, session_uuid: str, window: float) -> bool:
        now = self._wall()
        return any(j.caller_session == session_uuid and (j.state not in TERMINAL or now - j.created_at <= window) for j in store.list_jobs(limit=200))

    def _peer_free(self, store: Any, uid: str) -> bool:
        with closing(self._wired.open_db()) as conn:
            row = conn.execute("SELECT root FROM projects WHERE uid = ?", (uid,)).fetchone()
        if row is None:
            return False
        view = jobs_place.live_view(row[0], uid)
        policy = jobs_policy.get(store, uid)
        kept = [p for p in view.peers if not jobs_place.drop_reason(p, policy, view)]
        decision = placement_rule.decide(kept, placement_workload.resolve({"kind": "suite"}), project_uid=uid, company_uid=view.company_uid) if kept else None
        return bool(decision is not None and decision.chosen)

    def _counter_for(self, store: Any) -> miss_count.MissCounter:
        if self._counter is None:
            self._counter = miss_count.MissCounter(store, sessions_of_marked=lambda: self._marked_sessions(store),
                                                   recent_delegate=lambda u, w: self._recent_delegate(store, u, w),
                                                   peer_free=lambda uid: self._peer_free(store, uid))
        return self._counter

    def tick(self) -> None:
        try:
            store = jobs_boot.engine().store
        except JobError:
            return
        counter = self._counter_for(store)
        if not self._gauge.pegged():
            counter.observe([], {}, {}, False)
        else:
            procs = process_tree.read()
            got = session_demote.gather(self._wired.open_db, procs) if procs is not None else None
            if procs is not None and got is not None:
                counter.observe(procs, got[0], got[1], True)
        if self._clock() - self._flushed >= self.FLUSH_SECONDS:
            self._flushed = self._clock()
            store.load_hours_put(self._gauge.hours(), keep_since_hour=int(self._wall() // 3600) - jobs_metrics.KEEP_DAYS * 24)


async def run(app_state: Any, wired: Any, throttle: throttle_mod.Throttle, *, tick: float = throttle_mod.TICK_SECONDS,
              extra: Sequence[throttle_mod.Throttle] = (), gauge: Optional[pressure.Gauge] = None,
              metrics_beat: Optional[MetricsBeat] = None) -> None:
    for each in (throttle, *extra):
        await asyncio.to_thread(each.boot_clear)
    while True:
        await asyncio.sleep(tick)
        try:
            for each in (throttle, *extra):
                await asyncio.to_thread(each.tick)
            if gauge is not None:
                await asyncio.to_thread(gauge.tick)
            if metrics_beat is not None:
                try:
                    await asyncio.to_thread(metrics_beat.tick)
                except (sqlite3.Error, JobError, OSError) as exc:
                    logger.warning("pack_metrics_beat_failed", error=type(exc).__name__)
            waiting = await asyncio.to_thread(_count_waiting, wired.open_db)
            if waiting and swarm_switch.is_on():
                await drain(app_state, wired.open_db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack_maintenance_beat_failed", error=type(exc).__name__)


def throttle_roots(panes: attached.BodyPanes, *, jobs_socket: str = jobs_paths.JOBS_TMUX_SOCKET) -> List[int]:
    try:
        job_pids = jobs_runner.pane_pids(socket=jobs_socket)
    except JobError as exc:
        logger.warning("pack_maintenance_job_panes_unread", code=exc.code)
        job_pids = []
    return panes.loose() + job_pids


def shared_measure(wired: Any, *, clock: Callable[[], float] = time.monotonic, max_age: float = 5.0
                   ) -> Callable[[], Optional[Tuple[float, float, int]]]:
    cached: List[Any] = [float("-inf"), None]

    def measure() -> Optional[Tuple[float, float, int]]:
        if clock() - cached[0] >= max_age:
            cached[0], cached[1] = clock(), throttle_mod.measure_local(wired)
        return cached[1]

    return measure


def build_gauge(measure: Callable[[], Optional[Tuple[float, float, int]]], throttles: Sequence[throttle_mod.Throttle],
                holds: holds_mod.Holds = holds_mod.HOLDS) -> pressure.Gauge:
    system = platform.system()
    return pressure.Gauge(measure, lambda: pressure.read_mem_pressure(system), lambda: pressure.read_run_queue(os.cpu_count() or 0, system),
                          lambda: len(frozenset().union(*(t.held_pids() for t in throttles))), holds)


def start(app: Any, wired: Any) -> "asyncio.Task[None]":
    measure = shared_measure(wired)
    panes = attached.BodyPanes(wired.open_db, viewing=attached.make_viewing(lambda: getattr(app.state, "session_manager", None)))
    throttle = throttle_mod.Throttle(measure=measure, roots=lambda: throttle_roots(panes), exempt=panes.attached)
    demote = session_demote.build(wired)
    gauge = build_gauge(measure, (throttle, demote))
    wired.runtime.collector.add_extra("pressure", gauge.view)
    return asyncio.create_task(run(app.state, wired, throttle, extra=(demote,), gauge=gauge, metrics_beat=MetricsBeat(wired, gauge)),
                               name="pack-reserve-maintenance")

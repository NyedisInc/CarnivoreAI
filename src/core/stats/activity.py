from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.core.pipeline.plugin_db import lock_for
from src.core.session_timeline import push as timeline_push
from src.core.stats.plugin import PLUGIN_ID, live



@dataclass(frozen=True)
class ActivityPoint:
    instance: str
    conversation_id: str
    provider: str
    project: str
    model: str
    host: str
    state: str
    observed_at: float
    running: bool | None
    created_at: float = 0
    agent_kind: str = 'session'
    subagents: int | None = None

    @property
    def dimensions(self) -> tuple[str, ...]:
        return (self.host, self.provider, self.conversation_id, self.project,
                self.model, self.agent_kind)


_WAITING_STATES = ('question', 'notice')
_BAND_METRICS = frozenset({'observed_seconds', 'working_seconds'})


_OBSERVED_METRICS = ('observed_seconds', 'average_working_agents', 'average_running_agents')
_WORKING_METRICS = ('working_seconds', 'average_working_agents')
_RUNNING_METRICS = ('running_seconds', 'average_running_agents')


def _pieces(start: float, end: float) -> Iterable[tuple[int, float]]:
    while start < end:
        minute = int(start // 60) * 60
        stop = min(end, minute + 60)
        yield minute, stop - start
        start = stop


class ActivityRecorder:

    def __init__(self, store: Any) -> None:
        self.store = store
        self.previous: dict[str, ActivityPoint] = {}
        self.previous_at: float | None = None
        self.changed: set[str] = set()

    def reset(self) -> None:
        self.previous = {}
        self.previous_at = None

    def record(self, points: list[ActivityPoint], at: float,
               quota: list[dict[str, Any]]) -> set[str]:
        self.changed = set()
        current = {p.instance: p for p in points}
        with lock_for(PLUGIN_ID), self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            enabled = db.execute('SELECT enabled FROM stats_settings WHERE singleton=1').fetchone()
            if enabled is None or not enabled[0]:
                self.reset()
                return self.changed
            for point in current.values():
                old = self.previous.get(point.instance)
                if old is None or point.conversation_id != old.conversation_id:
                    if self.previous_at is not None and self.previous_at < point.created_at <= at:
                        self._write(db, int(point.created_at // 60) * 60, point, starts=1)
                    continue
                elapsed = point.observed_at - old.observed_at
                if not 0 < elapsed <= 30 or old.running is None or point.running is None:
                    continue
                if db.execute('SELECT 1 FROM stats_disabled_spans WHERE start_ts<? AND '
                              '(end_ts IS NULL OR end_ts>?) LIMIT 1',
                              (point.observed_at, old.observed_at)).fetchone():
                    continue
                for minute, seconds in _pieces(old.observed_at, point.observed_at):
                    known = old.state != 'unknown' and point.state != 'unknown'
                    self._write(db, minute, old,
                                observed=seconds if known else 0,
                                working=seconds if known and old.state in ('working', 'working_subagent') else 0,
                                running=seconds if old.running else 0,
                                waiting=seconds if known and old.state in _WAITING_STATES else 0,
                                subagent=seconds if known and (old.state == 'working_subagent'
                                                               or (old.subagents or 0) > 0) else 0)
                if old.running and not point.running:
                    self._write(db, int(point.observed_at // 60) * 60, point, completions=1)
            uninterrupted = self.previous_at is not None and not db.execute(
                'SELECT 1 FROM stats_disabled_spans WHERE start_ts<? AND '
                '(end_ts IS NULL OR end_ts>?) LIMIT 1', (at, self.previous_at)).fetchone()
            if uninterrupted and 0 < at - self.previous_at <= 30:
                self.changed.add('average_running_agents')
                for minute, seconds in _pieces(self.previous_at, at):
                    live.add_coverage(db, minute, seconds)
            for q in quota:
                if db.execute('SELECT 1 FROM stats_disabled_spans WHERE start_ts<=? AND '
                              '(end_ts IS NULL OR end_ts>?) LIMIT 1',
                              (q['minute_ts'], q['minute_ts'])).fetchone():
                    continue
                held = db.execute('SELECT utilization FROM quota_minutes WHERE minute_ts=? AND account_id=? '
                                  'AND window=? AND reset_at=?',
                                  (q['minute_ts'], q['account_id'], q['window'], q['reset_at'])).fetchone()
                if held is None or held[0] != q['utilization']:
                    self.changed.add('quota_utilization')
                live.put_quota(db, q)
            live.retain(db, at)
            db.execute("UPDATE stats_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
        if self.changed & _BAND_METRICS:
            timeline_push.announce_activity()
        self.previous = current
        self.previous_at = at
        return self.changed

    def _write(self, db: Any, minute: int, point: ActivityPoint, *, observed: float = 0,
               working: float = 0, running: float = 0, starts: int = 0,
               completions: int = 0, waiting: float = 0, subagent: float = 0) -> None:
        for amount, metrics in ((observed, _OBSERVED_METRICS), (working, _WORKING_METRICS),
                                (running, _RUNNING_METRICS), (starts, ('starts',)),
                                (completions, ('completions',)), (waiting, ('waiting_seconds',)),
                                (subagent, ('subagent_seconds',))):
            if amount:
                self.changed.update(metrics)
        live.add_activity(db, minute, point.dimensions,
                          (observed, working, running, starts, completions, waiting, subagent))

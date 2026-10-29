from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time

from pathlib import Path
from typing import Any

import structlog

from src.core.db import db_path_for
from src.core.session_change_notice import publish
from . import activity, changes, config, events, observations, rules, tripwires
from .plugin import PLUGIN_ID, ingest
from .account_owner import AccountAttribution
from .store import StatsStore

logger = structlog.get_logger()


class StatsScheduler:

    def __init__(self, store: StatsStore, manager: Any, app_state: Any, config_path: Path) -> None:
        self.store, self.manager, self.app_state = store, manager, app_state
        self.config_path = config_path
        ingest.set_account_resolver(AccountAttribution(config_path))
        self.activity = activity.ActivityRecorder(store)
        self.rules = rules.RuleObserver(store)
        self._cancel = threading.Event()
        self._reset_observations = threading.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_projects = 0.0
        self._last_rules = 0.0
        self._last_notice = 0.0
        self._last_chart_notice = 0.0
        self._noticed_live: dict | None = None
        self._noticed_event_id = -1
        self._noticed_sides: dict | None = None
        self._held_changes = changes.PassChanges()
        self._last_tripwires = 0.0
        self._backfill_running = False
        self._enabled = False
        self._live: dict = {'state': 'pending', 'as_of': None, 'metrics': {}}
        self._status: dict = {'state': 'pending', 'last_success': None}
        self._stale_reported = False

    def start(self) -> bool:
        if os.environ.get('CLOUDE_TEST_MODE') or self._task is not None:
            return False
        self._task = asyncio.create_task(self._run(), name='stats-collector')
        return True

    def settings_changed(self, value: dict) -> None:
        self._reset_observations.set()
        if not value['enabled']:
            self._live = {'state': 'disabled', 'as_of': None, 'metrics': {}}
        self._wake.set()

    def after_clear(self) -> None:
        self._noticed_live, self._noticed_event_id = None, -1
        self._reset_observations.set()
        self._wake.set()

    def request_backfill(self) -> dict:
        if not self._backfill_running:
            self._backfill_running = True
            asyncio.get_running_loop().create_task(self._rebuild(), name='stats-rebuild')
        return {'state': 'requested'}

    async def _rebuild(self) -> None:
        from src.core.pipeline import plugin_db, runtime
        from src.core.pipeline import rebuild as pipeline_rebuild
        state = 'complete'
        try:
            await asyncio.to_thread(runtime.rebuild_plugin, PLUGIN_ID)
        except (OSError, sqlite3.Error, plugin_db.PluginUnavailable, pipeline_rebuild.UnknownPlugin) as exc:
            logger.warning('stats_rebuild_failed', error_type=type(exc).__name__)
            state = 'failed'
        finally:
            self._backfill_running = False
        await asyncio.to_thread(self._close_backfills, state)
        self.after_clear()

    def _close_backfills(self, state: str) -> None:
        with self.store.connect() as db:
            db.execute("UPDATE stats_backfill SET state=?,updated_at=? WHERE state IN ('requested','running')",
                       (state, int(time.time())))

    def live_snapshot(self) -> dict:
        result = dict(self._live)
        if result.get('state') == 'ok' and time.time() - self._status.get('last_success', 0) > 45:
            result['state'] = 'stale'
        return result

    def status(self) -> dict:
        return {**self._status, 'rules_state': self.rules.last_state,
                'backfill_running': self._backfill_running}

    async def aclose(self) -> None:
        self._cancel.set()
        self._wake.set()
        if self._task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=15)
        except asyncio.TimeoutError:
            logger.warning('stats_shutdown_timeout')
            self._task.cancel()
        self._task = None

    def _refresh_projects(self) -> None:
        from src.core.db import connect
        from src.core.project_store import list_projects
        from src.core.hosts.identity import is_remote_root
        db = connect(db_path_for(self.store.state_dir))
        try:
            self.rules.add_projects([row['root'] for row in list_projects(db)
                                     if not is_remote_root(row['root'])])
        finally:
            db.close()
        self._last_projects = time.monotonic()

    def _collect(self, points: list, sampled_at: float, quota: list,
                 hints: list[tuple[str, str, str]]) -> dict:
        enabled = config.get_settings(self.store)['enabled']
        if not enabled:
            self.activity.reset()
            self._enabled = False
            return {'state': 'disabled'}
        if not self._enabled:
            self.activity.reset()
        self._enabled = True
        if self._cancel.is_set():
            return {'state': 'stopping'}
        if time.monotonic() - self._last_projects >= 900:
            self._refresh_projects()
        self.rules.add_projects([cwd for _, _, cwd in hints if cwd])
        if self._reset_observations.is_set():
            self.activity.reset()
            self._reset_observations.clear()
        moved: set[str] = set()
        if self.activity.previous_at != sampled_at:
            moved = self.activity.record(points, sampled_at, quota)
        if time.monotonic() - self._last_rules >= 60:
            self.rules.run_batch()
            self._last_rules = time.monotonic()
        return {'state': 'ok', 'published_sources': ingest.take_moved(), 'activity_metrics': sorted(moved),
                'last_success': time.time()}

    async def _notice(self, result: dict, live_metrics: dict) -> None:
        event_id = await asyncio.to_thread(changes.last_event_id, self.store)
        sides = await asyncio.to_thread(changes.side_fingerprints, self.store)
        found = changes.summarise(
            published_sources=int(result.get('published_sources') or 0),
            activity_metrics=result.get('activity_metrics') or (),
            live_before=self._noticed_live, live_after=live_metrics,
            events_before=self._noticed_event_id, events_after=event_id,
            sides_before=self._noticed_sides, sides_after=sides)
        self._held_changes = self._merge_held(found)
        now = time.monotonic()
        since_chart = now - self._last_chart_notice
        if not self._held_changes.due(now - self._last_notice, since_chart):
            return
        sending = self._held_changes.for_frame(since_chart)
        revision = await asyncio.to_thread(self.store.revision)
        publish(self.app_state, {'type': 'stats.changed', 'revision': revision, 'source_health': 'ok',
                                 'changed': sending.frame_field()})
        self._last_notice = now
        if sending.metrics:
            self._last_chart_notice = now
        self._noticed_live = dict(live_metrics)
        self._noticed_event_id = event_id
        self._noticed_sides = sides
        self._held_changes = changes.PassChanges(metrics=self._held_changes.metrics - sending.metrics)

    def _merge_held(self, found: changes.PassChanges) -> changes.PassChanges:
        held = self._held_changes
        return changes.PassChanges(metrics=held.metrics | found.metrics, live=found.live,
                                   events=found.events, dimensions=found.dimensions,
                                   coverage=found.coverage, tripwires=found.tripwires)

    async def _run(self) -> None:
        sampled_at = 0.0
        points, live, quota, hints = [], {}, [], []
        while not self._cancel.is_set():
            delay = 15
            try:
                enabled = await asyncio.to_thread(config.get_settings, self.store)
                if enabled['enabled']:
                    if time.time() - sampled_at >= 15 or self._reset_observations.is_set():
                        points, live, quota, hints = await observations.sample(self.manager, self.store.state_dir)
                        sampled_at = time.time()
                    result = await asyncio.to_thread(self._collect, points, sampled_at, quota, hints)
                    if result['state'] == 'ok':
                        metrics = {k: v for k, v in live.items() if k not in ('state', 'as_of', 'activity_basis', 'subagents_coverage')}
                        self._live = {**live, 'metrics': metrics}
                        await self._notice(result, metrics)
                        if time.monotonic() - self._last_tripwires >= 30:
                            self._last_tripwires = time.monotonic()
                            for frame in await asyncio.to_thread(tripwires.evaluate_all, self.store):
                                publish(self.app_state, frame)
                else:
                    await asyncio.to_thread(self.activity.reset)
                    self._enabled = False
                    self._live = {'state': 'disabled', 'as_of': None, 'metrics': {}}
                    result = {'state': 'disabled'}
                self._status.update(result)
                if result.get('state') == 'ok':
                    self._stale_reported = False
            except (OSError, sqlite3.Error, ValueError, RuntimeError, TimeoutError) as exc:
                logger.warning('stats_collection_failed', error_type=type(exc).__name__)
                self._status.update(state='error', error=type(exc).__name__)
                if not self._stale_reported:
                    self._stale_reported = True
                    await asyncio.to_thread(events.record, 'collector_stale', '',
                                            {'reason': type(exc).__name__}, store=self.store)
                self._live = {'state': 'error', 'as_of': self._live.get('as_of'), 'metrics': {}}
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

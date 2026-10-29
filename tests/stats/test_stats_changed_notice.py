import asyncio
import time
from types import SimpleNamespace

from src.core.stats import scheduler as scheduler_module
from src.core.stats.activity import ActivityPoint, ActivityRecorder
from src.core.stats.changes import USAGE_METRICS
from src.core.stats.scheduler import StatsScheduler
from tests.stats.test_observations import ready


def _point(at, state, running=True):
    return ActivityPoint(instance='one', conversation_id='conversation', provider='claude', project='project',
                         model='model', host='local', state=state, observed_at=at, running=running)


def test_stats_changed_is_sent_only_on_a_change_and_names_the_metrics(tmp_path, monkeypatch):
    store = ready(tmp_path)

    recorder = ActivityRecorder(store)
    quota = dict(minute_ts=120, account_id='a', provider='claude', window='five_hour', reset_at='r',
                 utilization=40.0, fetched_at='2026-09-30T00:00:00Z', state='ok')
    recorder.record([_point(100, 'idle')], 100, [quota])
    idle = recorder.record([_point(110, 'idle')], 110, [dict(quota, fetched_at='2026-09-30T00:01:00Z')])
    assert 'working_seconds' not in idle and 'quota_utilization' not in idle
    assert 'observed_seconds' in idle
    moved = recorder.record([_point(120, 'working')], 120, [dict(quota, utilization=41.0,
                                                                    fetched_at='2026-09-30T00:02:00Z')])
    assert 'quota_utilization' in moved and 'working_seconds' not in moved
    assert 'working_seconds' in recorder.record([_point(130, 'working')], 130, [])

    sent = []
    monkeypatch.setattr(scheduler_module, 'publish', lambda _state, frame: sent.append(frame))
    sched = StatsScheduler(store, object(), SimpleNamespace(), tmp_path / 'config.json')
    live = {'working': 0, 'active_models': 1}
    quiet = {'published_sources': 0, 'activity_metrics': []}

    async def drive():
        await sched._notice(quiet, live)
        sched._last_notice = 0.0
        await sched._notice(quiet, dict(live))
        sched._last_notice = 0.0
        await sched._notice({'published_sources': 0, 'activity_metrics': ['working_seconds']}, live)
        await sched._notice({'published_sources': 2, 'activity_metrics': []}, live)
        sched._last_notice = 0.0
        sched._last_chart_notice = 0.0
        await sched._notice(quiet, {'working': 1, 'active_models': 1})
        idle_pass = {'published_sources': 0, 'activity_metrics': ['observed_seconds', 'running_seconds']}
        live_now = {'working': 1, 'active_models': 1}
        sched._last_notice = time.monotonic() - 20
        await sched._notice(idle_pass, live_now)
        assert len(sent) == 3
        sched._last_notice = time.monotonic() - 61
        sched._last_chart_notice = time.monotonic() - 61
        await sched._notice(idle_pass, live_now)

    asyncio.run(drive())
    assert len(sent) == 4
    assert all(f['type'] == 'stats.changed' for f in sent)
    assert sent[1]['changed'] == {'metrics': ['working_seconds'], 'live': False, 'events': False,
                                  'dimensions': False, 'coverage': False, 'tripwires': False,
                                  'clock_only': False}
    assert set(sent[2]['changed']['metrics']) == set(USAGE_METRICS)
    assert sent[2]['changed']['live'] is True
    assert sent[2]['changed']['dimensions'] is False and sent[2]['changed']['coverage'] is False
    assert sent[3]['changed']['clock_only'] is True
    assert sent[3]['changed']['metrics'] == ['observed_seconds', 'running_seconds']

    with store.connect() as db:
        db.execute("INSERT INTO dim_model(name) VALUES ('brand-new-model')")

    async def new_value():
        sched._last_notice = 0.0
        await sched._notice({'published_sources': 1, 'activity_metrics': []}, {'working': 1, 'active_models': 1})

    asyncio.run(new_value())
    assert len(sent) == 5
    assert sent[4]['changed']['dimensions'] is True
    assert sent[4]['changed']['coverage'] is False and sent[4]['changed']['tripwires'] is False


def test_chart_metrics_ride_at_most_one_frame_a_minute_but_live_parts_keep_15_s(tmp_path, monkeypatch):
    store = ready(tmp_path)
    sent = []
    monkeypatch.setattr(scheduler_module, 'publish', lambda _state, frame: sent.append(frame))
    sched = StatsScheduler(store, object(), SimpleNamespace(), tmp_path / 'config.json')
    working = {'published_sources': 0, 'activity_metrics': ['working_seconds']}
    live = {'working': 1}

    async def drive():
        await sched._notice(working, live)
        assert len(sent) == 1 and sent[0]['changed']['metrics'] == ['working_seconds']
        sched._last_notice = time.monotonic() - 20
        await sched._notice(working, live)
        assert len(sent) == 1
        sched._last_notice = time.monotonic() - 20
        await sched._notice(working, {'working': 2})
        assert len(sent) == 2
        assert sent[1]['changed']['metrics'] == [] and sent[1]['changed']['live'] is True
        sched._last_notice = time.monotonic() - 20
        sched._last_chart_notice = time.monotonic() - 61
        await sched._notice({'published_sources': 0, 'activity_metrics': []}, {'working': 2})
        assert len(sent) == 3 and sent[2]['changed']['metrics'] == ['working_seconds']

    asyncio.run(drive())

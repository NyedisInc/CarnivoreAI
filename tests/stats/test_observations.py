from pathlib import Path

from src.core.stats import activity, config, rules
from src.core.stats.activity import ActivityPoint, ActivityRecorder
from src.core.stats.store import StatsStore


def ready(tmp_path):
    store = StatsStore(tmp_path)
    store.initialize()
    config.ensure_schema(store)
    settings = config.get_settings(store)
    config.update_settings(store, enabled=True, revision=settings['revision'])
    rules.initialize(store)
    return store


def point(at, state='working', instance='one'):
    return ActivityPoint(instance=instance, conversation_id='conversation', provider='claude',
                         project='project', model='model', host='local', state=state,
                         observed_at=at, running=True)


def test_minute_split_gaps_pause_and_quota_are_metadata_only(tmp_path):
    store = ready(tmp_path)
    recorder = ActivityRecorder(store)
    quota = dict(minute_ts=120, account_id='account', provider='claude', window='five_hour',
                 reset_at='2026-10-01T00:00:00Z', utilization=37.5,
                 fetched_at='2026-09-29T00:00:00Z', state='ok')
    recorder.record([point(115)], 115, [quota])
    recorder.record([point(130)], 130, [quota])
    recorder.record([point(190)], 190, [quota])
    with store.connect(readonly=True) as db:
        assert [(r['minute_ts'], r['working_seconds']) for r in db.execute('SELECT * FROM activity_minutes ORDER BY minute_ts')] == [(60, 5), (120, 10)]
        assert db.execute('SELECT COUNT(*) FROM quota_minutes').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM sqlite_master WHERE name LIKE "transcript_%"').fetchone()[0] == 0
    settings = config.get_settings(store)
    config.update_settings(store, enabled=False, revision=settings['revision'])
    recorder.record([point(205)], 205, [])
    settings = config.get_settings(store)
    config.update_settings(store, enabled=True, revision=settings['revision'])
    recorder.record([point(220)], 220, [])
    with store.connect(readonly=True) as db:
        assert db.execute('SELECT SUM(working_seconds) FROM activity_minutes').fetchone()[0] == 15


def test_unknown_observation_never_counts_as_measured_work(tmp_path):
    store = ready(tmp_path)
    recorder = ActivityRecorder(store)
    recorder.record([point(120, 'unknown')], 120, [])
    recorder.record([point(135)], 135, [])
    with store.connect(readonly=True) as db:
        row = db.execute('SELECT * FROM activity_minutes').fetchone()
        assert row['observed_seconds'] == 0 and row['working_seconds'] == 0
        assert row['running_seconds'] == 15


def test_rule_observer_keeps_hashes_only_and_repeated_hash_is_noop(tmp_path):
    store = ready(tmp_path / 'state')
    rule = tmp_path / 'AGENTS.md'
    secret_content = 'PROMPT-BODY-MUST-NOT-BE-STORED-8361'
    rule.write_text(secret_content)
    observer = rules.RuleObserver(store, [rule])
    observer.run_batch(now=100)
    observer.run_batch(now=200)
    with store.connect(readonly=True) as db:
        assert db.execute('SELECT COUNT(*) FROM stats_annotations').fetchone()[0] == 1
        row = db.execute('SELECT * FROM stats_annotations').fetchone()
        assert row['basis'] == 'observed' and row['reference'] == 'AGENTS.md'
        assert len(row['rule_hash']) == 64
        dump = '\n'.join(db.iterdump())
        assert secret_content not in dump
    rule.write_text(secret_content + '\nchanged')
    observer.run_batch(now=300)
    with store.connect(readonly=True) as db:
        assert db.execute('SELECT COUNT(*) FROM stats_annotations').fetchone()[0] == 2
    rule.unlink()
    observer.run_batch(now=400)
    observer.run_batch(now=500)
    with store.connect(readonly=True) as db:
        assert db.execute('SELECT COUNT(*) FROM stats_annotations').fetchone()[0] == 3
        assert db.execute('SELECT label FROM stats_annotations ORDER BY occurred_at DESC').fetchone()[0] == 'AGENTS.md: removal observed'


def test_future_stats_schema_does_not_prevent_app_start(tmp_path):
    import asyncio
    import sqlite3
    from types import SimpleNamespace
    from src.core.stats.wiring import start_stats
    plugin_dir = tmp_path / 'pipeline-plugins'
    plugin_dir.mkdir()
    with sqlite3.connect(plugin_dir / 'stats.db') as db:
        db.execute('CREATE TABLE plugin_meta (key TEXT PRIMARY KEY, value TEXT)')
        db.execute("INSERT INTO plugin_meta VALUES ('schema_version', '999')")
    state = SimpleNamespace()
    asyncio.run(start_stats(state, object(), tmp_path, tmp_path / 'config.json'))
    assert state.stats_store is None and state.stats_scheduler is None


def test_disabled_span_blocks_quota_and_observation_coverage(tmp_path):
    store = ready(tmp_path)
    recorder = ActivityRecorder(store)
    recorder.record([point(120)], 120, [])
    with store.connect() as db:
        db.execute('INSERT INTO stats_disabled_spans(start_ts,end_ts) VALUES (120,180)')
    recorder.record([point(135)], 135, [dict(minute_ts=120, account_id='account', provider='claude',
        window='five_hour', reset_at='', utilization=20, fetched_at='2026-09-29T00:00:00Z', state='ok')])
    with store.connect(readonly=True) as db:
        assert db.execute('SELECT COUNT(*) FROM activity_minutes').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM stats_observation_coverage').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM quota_minutes').fetchone()[0] == 0


def test_scheduler_recovers_after_a_failed_pass(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from src.core.stats.scheduler import StatsScheduler
    store = ready(tmp_path)
    settings = config.get_settings(store)
    config.update_settings(store, enabled=False, revision=settings['revision'])
    with store.connect() as db:
        db.execute('DROP TABLE stats_settings')
    scheduler = StatsScheduler(store, object(), SimpleNamespace(), tmp_path / 'config.json')
    async def exercise():
        task = asyncio.create_task(scheduler._run())
        await asyncio.sleep(0.1)
        assert not task.done()
        assert scheduler.status()['state'] == 'error'
        config.ensure_schema(store)
        scheduler.settings_changed({'enabled': False})
        await asyncio.sleep(0.1)
        assert not task.done()
        assert scheduler.status()['state'] == 'disabled'
        scheduler._cancel.set()
        scheduler._wake.set()
        await asyncio.wait_for(task, timeout=1)
    asyncio.run(exercise())

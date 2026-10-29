from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.core.db import transaction
from src.core.pipeline import contract as PK
from src.core.pipeline import inherit as inheritance
from src.core.pipeline import plugin_db as host
from src.core.pipeline.contract import Appended, FileReset
from src.core.stats import answers, config, queries
from src.core.stats.activity import ActivityRecorder
from src.core.stats.plugin import ingest, usage_revision
from src.core.stats.plugin.pipeline_plugin import STATS
from src.core.transcript_contract import parse_range
from src.models.stats import AnnotationWrite
from tests.stats.test_batch_live import _client, _item, _row
from tests.stats.test_observations import point
from tests.stats.test_stats_plugin import CONV, _assistant, _blob

USAGE = "total_tokens"
ACTIVITY = "working_seconds"


@pytest.fixture
def env(tmp_path, monkeypatch):
    _client_, store = _client(tmp_path)
    _row(store, int(time.time()) // 60 * 60, "c1")
    monkeypatch.setattr(answers._Ledger, "state", lambda _self: answers.STATE_OK)
    answers._registry.clear()
    calls: List[str] = []
    real = queries.execute

    def counted(target: Any, request: Any, deadline: Any = None) -> dict:
        calls.append(request.metric)
        return real(target, request, deadline)

    monkeypatch.setattr(queries, "execute", counted)
    recorder = ActivityRecorder(store)
    clock = {"at": 1_000_000.0}

    def tick() -> None:
        for _ in range(2):
            clock["at"] += 5
            recorder.record([point(clock["at"])], clock["at"], [])

    def ask(metric: str) -> dict:
        got = queries.execute_batch(store, [{**_item(3600), "metric": metric}])
        answers.wait_idle()
        return got["results"][0]

    return SimpleNamespace(store=store, calls=calls, tick=tick, ask=ask, tmp=tmp_path)


def _ingest_usage(env: Any, name: str, out: int) -> None:
    conn = host.open_db(env.tmp, STATS)
    try:
        now = time.time()
        data = _blob([_assistant(int(now) - 30, name, out)])
        rng = parse_range(data, 0, "claude")
        _state, start, end = inheritance.advance(PK.INHERIT_HEAD, 0, 0, rng.lines, CONV)
        event = Appended(CONV, "claude", f"/t/{CONV}.jsonl", "conversation", 0, rng.complete_end, rng.lines, start, end, None, "test")
        with transaction(conn):
            ingest.appended(conn, event, now=now)
    finally:
        conn.close()


def test_an_activity_tick_does_not_recompute_a_usage_card(env):
    first = env.ask(USAGE)
    before_calls, before_revision = len(env.calls), env.store.revision()
    for _ in range(5):
        env.tick()
        again = env.ask(USAGE)
    assert env.store.revision() > before_revision
    assert len(env.calls) == before_calls
    assert again["answer"]["stale"] is False and again["result"] == first["result"]


def test_an_activity_tick_still_recomputes_an_activity_card(env):
    env.ask(ACTIVITY)
    base = len(env.calls)
    env.tick()
    stale = queries.execute_batch(env.store, [{**_item(3600), "metric": ACTIVITY}])["results"][0]
    answers.wait_idle()
    assert stale["answer"]["stale"] is True
    assert len(env.calls) == base + 1


def test_new_usage_through_ingest_recomputes_the_usage_card_and_changes_the_answer(env):
    _ingest_usage(env, "msg-one", 5)
    first = env.ask(USAGE)
    base = len(env.calls)
    _ingest_usage(env, "msg-two", 777)
    stale = queries.execute_batch(env.store, [{**_item(3600), "metric": USAGE}])["results"][0]
    assert stale["answer"] == {**stale["answer"], "stale": True, "reason": "refreshing"}
    answers.wait_idle()
    fresh = env.ask(USAGE)
    assert len(env.calls) == base + 1
    assert fresh["answer"]["stale"] is False
    assert fresh["result"]["summary"]["value"] > first["result"]["summary"]["value"]


def test_a_settings_write_recomputes_the_usage_card(env):
    env.ask(USAGE)
    base = len(env.calls)
    config.create_annotation(env.store, AnnotationWrite(
        occurred_at=datetime.now(timezone.utc), kind="manual", label="x"))
    queries.execute_batch(env.store, [{**_item(3600), "metric": USAGE}])
    answers.wait_idle()
    assert len(env.calls) == base + 1


def test_the_private_counter_never_reaches_the_client_and_an_old_row_recomputes_once(env):
    got = env.ask(USAGE)
    assert "_usage_revision" not in got["result"]
    again = env.ask(USAGE)
    assert "_usage_revision" not in again["result"]
    ledger = answers.ledger_for(env.store)
    key = queries._ledger_key(queries.QueryRequest.model_validate({**_item(3600), "metric": USAGE}))[0]
    row = ledger.read(queries.BatchStore(env.store), key)
    ledger.store_later(key, row.fingerprint, row.window_end, row.payload, time.time(), None)
    answers.wait_idle()
    base = len(env.calls)
    stale = queries.execute_batch(env.store, [{**_item(3600), "metric": USAGE}])["results"][0]
    answers.wait_idle()
    assert stale["answer"]["stale"] is True and len(env.calls) == base + 1
    env.ask(USAGE)
    assert len(env.calls) == base + 1


def test_a_card_reading_both_families_follows_either_counter():
    row = answers.Row("f", 0, 0.0, {"revision": 5}, None, None, 3)
    view = SimpleNamespace(usage_revision=lambda: 3, revision=lambda: 5)
    both = ("usage", "activity")
    assert answers._data_current(row, view, both)
    assert not answers._data_current(row, SimpleNamespace(usage_revision=lambda: 4, revision=lambda: 5), both)
    assert not answers._data_current(row, SimpleNamespace(usage_revision=lambda: 3, revision=lambda: 6), both)
    assert answers._data_current(row, SimpleNamespace(usage_revision=lambda: 3, revision=lambda: 6), ("usage",))
    assert answers._data_current(row, SimpleNamespace(usage_revision=lambda: 4, revision=lambda: 5), ("activity",))


def test_the_counter_is_a_plain_meta_row_that_reads_zero_until_bumped(env):
    with env.store.connect() as db:
        db.execute("DELETE FROM stats_meta WHERE key=?", (usage_revision.KEY,))
        assert usage_revision.read(db) == 0
        usage_revision.bump(db)
        usage_revision.bump(db)
        assert usage_revision.read(db) == 2


def test_a_dropped_file_makes_the_usage_card_stale_at_once(env):
    _ingest_usage(env, "msg-one", 5)
    _ingest_usage(env, "msg-two", 700)
    before = env.ask(USAGE)
    base = len(env.calls)
    conn = host.open_db(env.tmp, STATS)
    try:
        with transaction(conn):
            ingest.on_event(conn, FileReset(PK.EV_FILE_REWRITTEN, CONV, "claude", f"/t/{CONV}.jsonl", "conversation", 1, 1))
    finally:
        conn.close()
    stale = queries.execute_batch(env.store, [{**_item(3600), "metric": USAGE}])["results"][0]
    assert stale["answer"]["stale"] is True and stale["answer"]["reason"] == "refreshing"
    answers.wait_idle()
    after = env.ask(USAGE)
    assert len(env.calls) == base + 1
    assert after["result"]["summary"]["value"] < before["result"]["summary"]["value"]


def _bare_append(env: Any, **extra: Any) -> None:
    conn = host.open_db(env.tmp, STATS)
    try:
        now = time.time()
        line = {"type": "user", "sessionId": CONV, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 20)),
                "cwd": "/work/app", "uuid": f"u-{extra.get('version')}", "message": {"role": "user", "content": "hi"}, **extra}
        data = _blob([line])
        rng = parse_range(data, 0, "claude")
        _state, start, end = inheritance.advance(PK.INHERIT_HEAD, 0, 0, rng.lines, CONV)
        event = Appended(CONV, "claude", f"/t/{CONV}.jsonl", "conversation", 0, rng.complete_end, rng.lines, start, end, None, "test")
        with transaction(conn):
            ingest.appended(conn, event, now=now)
    finally:
        conn.close()


def _counter(env: Any) -> int:
    with env.store.connect(readonly=True) as db:
        return usage_revision.read(db)


def test_a_source_metadata_change_with_no_usage_row_moves_the_counter(env):
    _bare_append(env, version="2.1.1")
    moved = _counter(env)
    _bare_append(env, version="2.1.1")
    assert _counter(env) == moved
    _bare_append(env, version="2.1.2")
    assert _counter(env) > moved


def test_the_account_backfill_moves_the_counter(env):
    _bare_append(env, version="2.1.1")
    before = _counter(env)
    ingest.set_account_resolver(lambda family, conversation: "acct-1")
    try:
        _bare_append(env, version="2.1.1")
    finally:
        ingest.set_account_resolver(None)
    assert _counter(env) > before

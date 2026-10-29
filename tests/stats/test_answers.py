from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone

import pytest

from src.core.stats import answers, live_view, project_groups, queries
from src.core.stats.plugin import carry
from src.core.stats.plugin import progress as progress_mod
from src.core.stats.store import StatsStore
from src.models import stats as models
from tests.stats.test_batch_live import _client, _row

BASE = datetime(2026, 3, 8, 10, 0, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def env(tmp_path, monkeypatch):
    client, store = _client(tmp_path)
    _row(store, int(BASE) - 60, "c1")
    clock = {"now": BASE + 5}
    monkeypatch.setattr(answers, "_now", lambda: clock["now"])
    monkeypatch.setattr(models, "_clock", lambda: clock["now"])
    state = {"value": answers.STATE_OK, "fail": False}
    monkeypatch.setattr(answers, "plugin_state", lambda _store: state["value"])
    calls: list = []
    real = queries.execute

    def counted(target, request, deadline=None):
        calls.append(request.metric)
        if state["fail"]:
            raise queries.QueryLimit("forced failure")
        return real(target, request, deadline)

    monkeypatch.setattr(queries, "execute", counted)
    answers._registry.clear()

    class Env:
        pass

    e = Env()
    e.client, e.store, e.clock, e.state, e.calls, e.tmp = client, store, clock, state, calls, tmp_path

    def ask(*items):
        got = queries.execute_batch(store, list(items))
        answers.wait_idle()
        return got["results"]

    e.ask = ask
    e.rows = lambda: _ledger_rows(store)
    return e


def _ledger_rows(store) -> int:
    with store.connect(readonly=True) as db:
        try:
            return db.execute("SELECT COUNT(*) FROM stats_answers").fetchone()[0]
        except sqlite3.OperationalError:
            return 0


def _exact(ms: int, metric: str = "total_tokens") -> dict:
    end = datetime.fromtimestamp(BASE + 0.001 * ms, timezone.utc)
    start = datetime.fromtimestamp(BASE + 0.001 * ms - 7 * 86400, timezone.utc)
    return {"metric": metric, "operation": "summary", "from": start.isoformat(), "to": end.isoformat()}


ROLLING = {"metric": "total_tokens", "operation": "comparison", "rolling": "7d"}


def test_same_card_in_one_minute_computes_once(env):
    first = env.ask(ROLLING)[0]
    env.clock["now"] += 30
    second = env.ask(ROLLING)[0]
    assert env.calls == ["total_tokens"]
    assert first["result"] == second["result"] and second["answer"] == {**first["answer"]}
    assert first["result"]["summary"]["value"] == 150
    exact = [env.ask(_exact(ms))[0] for ms in (250, 731)]
    assert env.calls == ["total_tokens"] * 2
    assert exact[0]["result"] == exact[1]["result"] and env.rows() == 2


def test_new_usage_makes_a_fresh_row_stale_at_once_and_the_recompute_carries_it(env, monkeypatch):
    monkeypatch.setattr(answers._Ledger, "state", lambda _self: answers.STATE_OK)
    first = env.ask(ROLLING)[0]
    env.clock["now"] += 10
    with env.store.connect() as db:
        db.execute("UPDATE stats_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
    _row(env.store, int(BASE), "c1")
    served = env.ask(ROLLING)[0]
    assert served["answer"]["stale"] is True and served["answer"]["reason"] == "refreshing"
    assert served["result"] == first["result"]
    later = env.ask(ROLLING)[0]
    assert later["answer"]["stale"] is False and later["result"]["summary"]["value"] == 300


def test_failed_compute_serves_the_last_good_answer_flagged_stale(env):
    good = env.ask(ROLLING)[0]
    env.clock["now"] += 120
    env.state["fail"] = True
    stale = env.ask(ROLLING)[0]
    assert stale["answer"]["stale"] is True and stale["answer"]["reason"] == "refreshing"
    assert stale["result"] == good["result"]
    again = env.ask(ROLLING)[0]
    assert again["answer"]["stale"] is True and again["answer"]["reason"] == "compute_failed"
    assert again["result"]["summary"]["value"] == 150 and again["answer"]["as_of"] == good["answer"]["as_of"]
    with env.store.connect() as db:
        db.execute("INSERT INTO stats_disabled_spans VALUES (?, NULL)", (int(BASE) - 3600,))
    kept = env.ask(ROLLING)[0]
    assert kept["answer"]["stale"] is True and kept["answer"]["reason"] == "compute_failed"
    assert kept["result"] == good["result"]
    env.state["fail"] = False
    assert env.ask({**ROLLING, "metric": "input_tokens", "group_by": "nope"})[0]["ok"] is False


def test_a_fresh_process_answers_from_the_ledger_with_zero_computes(env):
    env.ask(ROLLING, _exact(0))
    assert len(env.calls) == 2 and env.rows() == 2
    answers._registry.clear()
    live_view._live_memo.clear()
    reopened = StatsStore(env.tmp)
    reopened.initialize()
    env.calls.clear()
    got = queries.execute_batch(reopened, [ROLLING, _exact(0)])["results"]
    assert env.calls == [] and all(r["ok"] and r["answer"]["stale"] is False for r in got)
    assert got[0]["result"]["summary"]["value"] == 150


def test_a_settings_fingerprint_change_recomputes(env, monkeypatch):
    grouped = {**ROLLING, "operation": "ranking", "group_by": "project"}
    env.ask(ROLLING, grouped)
    assert len(env.calls) == 2
    env.ask(ROLLING, grouped)
    assert len(env.calls) == 2
    with env.store.connect() as db:
        db.execute("INSERT INTO stats_disabled_spans VALUES (?, NULL)", (int(BASE) - 3600,))
    got = env.ask(ROLLING)[0]
    assert len(env.calls) == 3 and got["answer"]["stale"] is False
    real = project_groups.groups_for
    env.ask(grouped)
    base = len(env.calls)

    def renamed(store, **kw):
        groups = real(store, **kw)
        groups.labels = {**groups.labels, "ab" * 12: "renamed"}
        return groups

    monkeypatch.setattr(project_groups, "groups_for", renamed)
    env.ask(grouped)
    assert len(env.calls) == base + 1


def test_no_ledger_write_while_the_plugin_is_behind_or_unknown(env, monkeypatch):
    env.ask(ROLLING)
    assert env.rows() == 1
    env.state["value"] = answers.STATE_BEHIND
    env.clock["now"] += 5
    held = env.ask(ROLLING)[0]
    assert held["answer"]["stale"] is True and held["answer"]["reason"] == "rebuilding" and len(env.calls) == 1
    live = env.ask({**ROLLING, "metric": "output_tokens"})[0]
    assert live["ok"] and live["answer"]["reason"] == "catching_up" and env.rows() == 1
    env.state["value"] = answers.STATE_UNKNOWN
    env.ask({**ROLLING, "metric": "input_tokens"})
    assert env.rows() == 1
    answers._registry.clear()
    monkeypatch.undo()
    ledger = answers.ledger_for(env.store)
    monkeypatch.setattr(progress_mod, "cached_progress", lambda _dir, block=True: {"known_sources": 3, "pending_sources": 99})
    assert ledger.state() == answers.STATE_BEHIND
    monkeypatch.setattr(progress_mod, "cached_progress", lambda _dir, block=True: {"known_sources": 3, "pending_sources": 2})
    assert ledger.state() == answers.STATE_OK
    monkeypatch.setattr(progress_mod, "cached_progress", lambda _dir, block=True: None)
    assert ledger.state() == answers.STATE_UNKNOWN


def test_the_table_is_an_lru_and_a_busy_database_only_skips_the_write(env, monkeypatch):
    monkeypatch.setattr(answers, "MAX_ROWS", 3)
    for i in range(6):
        env.ask(_exact(0, "total_tokens") | {"filters": {"model": f"m{i}"}})
        env.clock["now"] += 1
    assert env.rows() == 3
    with env.store.connect(readonly=True) as db:
        kept = sorted(r[0] for r in db.execute("SELECT computed_at FROM stats_answers"))
    assert kept == [BASE + 8, BASE + 9, BASE + 10]
    monkeypatch.setattr(answers, "WRITE_BUSY_MS", 50)
    ingest = sqlite3.connect(env.store.db_path, isolation_level=None)
    ingest.execute("BEGIN IMMEDIATE")
    try:
        started = time.monotonic()
        answers.ledger_for(env.store)._write("k", "f", 1, b"x", 1.0)
        assert time.monotonic() - started < 2.0
    finally:
        ingest.execute("ROLLBACK")
        ingest.close()
    with env.store.connect(readonly=True) as db:
        assert db.execute("SELECT COUNT(*) FROM stats_answers WHERE key='k'").fetchone()[0] == 0


def test_a_rebuild_carries_the_ledger_and_a_clear_purges_it(env):
    env.ask(ROLLING)
    assert env.rows() == 1
    new = sqlite3.connect(":memory:")
    with sqlite3.connect(f"file:{env.store.db_path}?mode=ro", uri=True) as old:
        carry.carry_over(old, new)
    assert new.execute("SELECT COUNT(*) FROM stats_answers").fetchone()[0] == 1
    bare = sqlite3.connect(":memory:")
    carry.carry_over(bare, sqlite3.connect(":memory:"))
    answers.purge(env.store)
    assert env.rows() == 0

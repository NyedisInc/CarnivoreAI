
from __future__ import annotations

import time

from src.core.stats import answers, config
from src.core.stats.store import StatsStore
from src.core.stats_feed import reader
from tests.python.perf_conn_reuse.helpers import count_connects, opens_of

N = 40


def make_store(tmp_path) -> StatsStore:
    store = StatsStore(tmp_path / "state")
    store.initialize()
    config.ensure_schema(store)
    return store


def test_feed_probe_and_snapshot_open_one_connection_and_see_a_new_revision(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    opened = count_connects(monkeypatch)
    started = time.perf_counter()
    for i in range(N):
        revision, _identity = reader.read_probe(store)
        reader.read_snapshot(store, 1_800_000_000.0)
        with store.connect() as db:
            db.execute("UPDATE stats_meta SET value=? WHERE key='revision'", (str(revision + 1),))
            db.commit()
        assert reader.read_probe(store)[0] == revision + 1
    ms = (time.perf_counter() - started) * 1000
    reads = opens_of(opened, "mode=ro")
    print(f"\nstats feed: {3 * N} reads, {reads} read connects (before: {3 * N}), {ms:.0f} ms")
    assert reads == 1


def test_answers_writer_keeps_one_connection_and_every_write_lands(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    ledger = answers.ledger_for(store)
    ledger.store_later("warm", "f", 1, {"v": 0}, 1.0)
    answers.wait_idle()
    opened = count_connects(monkeypatch)
    for i in range(N):
        ledger.store_later(f"k{i}", "f", 1, {"v": i}, float(i))
        answers.wait_idle()
    writer_opens = opens_of(opened, "stats.db") - 0
    with store.connect() as db:
        stored = db.execute("SELECT COUNT(*) FROM stats_answers").fetchone()[0]
    print(f"\nanswers writer: {N} writes, {writer_opens} connects (before: {N})")
    assert stored == N + 1
    assert writer_opens == 0

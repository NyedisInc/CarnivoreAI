
from __future__ import annotations

import sqlite3

from src.core.stats_feed import reader
from tests.python.stats_feed.conftest import NOW, line


def _totals(env, feed):
    return env.client(feed).get("/api/v1/stats/feed", params={"window": "1h"}).json()["totals"]


def _rewrite_same_revision(env, identity: str) -> None:
    with env.store.connect() as db:
        db.execute("UPDATE usage_minute SET input = input + 100")
        db.execute("INSERT OR REPLACE INTO plugin_meta(key, value) VALUES ('created_at', ?)", (identity,))


def test_a_rebuilt_database_on_the_same_revision_reseeds(env):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    feed = env.feed()
    assert _totals(env, feed)["fresh"] == 4
    rev = reader.read_revision(env.store)
    _rewrite_same_revision(env, "rebuilt-1")
    assert reader.read_revision(env.store) == rev
    assert _totals(env, env.feed())["fresh"] == 104
    assert asyncio_run(feed.refresh()) is True
    assert feed._snap.db_identity == "rebuilt-1" and _totals(env, feed)["fresh"] == 104


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def test_snapshot_is_one_read_transaction(env, monkeypatch):
    env.deliver([line(NOW - 30, "a", fresh=4, write=5, read=6, out=7)])
    real = reader._sums
    seen = {"writes": 0}

    def sums_then_write(conn, table, since, cap):
        out = real(conn, table, since, cap)
        if table == "usage_minute":
            with sqlite3.connect(env.store.db_path, timeout=5) as other:
                other.execute("UPDATE usage_hour SET input = input + 1000")
                other.execute("UPDATE stats_meta SET value = value + 1 WHERE key='revision'")
            seen["writes"] += 1
        return out

    before = reader.read_snapshot(env.store, NOW)
    monkeypatch.setattr(reader, "_sums", sums_then_write)
    snap = reader.read_snapshot(env.store, NOW)
    assert seen["writes"] == 1
    assert reader.read_revision(env.store) == before.revision + 1
    assert snap.revision == before.revision and snap.hours == before.hours
    assert reader.read_snapshot(env.store, NOW).hours != before.hours

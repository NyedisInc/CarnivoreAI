
from __future__ import annotations

import sqlite3

from src.core.stats_feed import reader
from tests.python.stats_feed.conftest import NOW, line

USAGE = [(20, 11, 1000, 20000, 500), (100, 7, 0, 5000, 90), (700, 3, 200, 300, 40), (3 * 3600, 5, 5, 5, 5)]


def _fill(env) -> None:
    env.deliver([line(NOW - ago, f"m{i}", fresh=f, write=w, read=r, out=o) for i, (ago, f, w, r, o) in enumerate(USAGE)])


def _sql_sums(env, since: int) -> tuple:
    with sqlite3.connect(env.store.db_path.as_uri() + "?mode=ro", uri=True) as db:
        return db.execute("SELECT SUM(input), SUM(cache_write), SUM(cache_read), SUM(output) FROM usage_minute "
                          "WHERE t >= ?", (since,)).fetchone()


def test_totals_and_bars_equal_sql_through_the_real_plugin(env):
    _fill(env)
    client = env.client(env.feed())
    doc = client.get("/api/v1/stats/feed", params={"window": "1h"}).json()
    start = doc["start"]
    expected = _sql_sums(env, start)
    t = doc["totals"]
    assert (t["fresh"], t["cache_write"], t["cache_read"], t["out"]) == expected
    assert (t["fresh"], t["cache_write"], t["cache_read"], t["out"]) == (11 + 7 + 3, 1200, 25300, 630)
    assert doc["state"] == "ok" and doc["sources"][0]["state"] == "ok"
    for ago, f, w, r, o in USAGE[:3]:
        i = (int((NOW - ago) // 60) * 60 - start) // 60
        assert doc["in"][i] == f + w + r and doc["out"][i] == o
    assert len(doc["in"]) == len(doc["out"]) == 60 and doc["rev"] == reader.read_revision(env.store)
    assert doc["rate"]["out"] > 0 and doc["rate"]["span_seconds"] >= 240


def test_dropping_a_class_from_the_reader_would_be_red(env, monkeypatch):
    _fill(env)
    monkeypatch.setattr(reader, "_SUMS", reader._SUMS.replace("SUM(cache_read)", "0"))
    doc = env.client(env.feed()).get("/api/v1/stats/feed", params={"window": "1h"}).json()
    assert doc["totals"]["cache_read"] == 0 != _sql_sums(env, doc["start"])[2]

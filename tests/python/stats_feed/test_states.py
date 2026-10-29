
from __future__ import annotations

import dataclasses

from src.core.stats import config
from tests.python.stats_feed.conftest import NOW, line


def _doc(env, feed=None):
    response = env.client(feed or env.feed()).get("/api/v1/stats/feed", params={"window": "1h"})
    assert response.status_code == 200
    return response.json()


def test_stats_off_is_a_named_state_with_no_numbers(env):
    env.deliver([line(NOW - 30, "a", fresh=1, write=2, read=3, out=4)])
    settings = config.get_settings(env.store)
    config.update_settings(env.store, enabled=False, revision=settings["revision"])
    doc = _doc(env)
    assert doc["state"] == "stats_off" and doc["sources"][0]["state"] == "stats_off"
    assert doc["totals"] is None and doc["rate"] is None and set(doc["in"]) == {None} == set(doc["out"])


def test_unreadable_database_is_unavailable_not_zero(env):
    feed = env.feed()
    feed._store_for = lambda: None
    doc = _doc(env, feed)
    assert doc["state"] == "unavailable" and doc["totals"] is None and set(doc["in"]) == {None}


def test_ignoring_the_enabled_switch_would_be_red(env, monkeypatch):
    from src.core.stats_feed import feed as feed_module

    env.deliver([line(NOW - 30, "a", fresh=1, write=2, read=3, out=4)])
    settings = config.get_settings(env.store)
    config.update_settings(env.store, enabled=False, revision=settings["revision"])
    real = feed_module.read_snapshot
    monkeypatch.setattr(feed_module, "read_snapshot", lambda s, n: dataclasses.replace(real(s, n), enabled=True))
    assert _doc(env)["state"] != "stats_off"

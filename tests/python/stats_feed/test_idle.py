
from __future__ import annotations

import asyncio
import time

import pytest

from src.core.stats_feed import feed as feed_module
from tests.python.stats_feed.conftest import NOW, line


def test_no_lease_no_task_no_read(env):
    reads = []
    feed = env.feed()
    original = env.store.connect
    env.store.connect = lambda **kw: reads.append(kw) or original(**kw)
    for _ in range(100):
        feed.on_hub_frame("resources.changed")
        feed.on_hub_frame("stats.changed")
        feed.mark_dirty("test")
    assert reads == [] and env.notified == [] and not feed.running and feed.counters["refreshes"] == 0


def test_leased_hub_frame_wakes_one_refresh_and_names_the_topic_only_when_it_changed(env, monkeypatch):
    monkeypatch.setattr(feed_module, "REFRESH_FLOOR_S", 0.0)

    async def go():
        env.deliver([line(NOW - 30, "a", fresh=1, write=0, read=0, out=1)])
        feed = env.feed()
        await feed.body("1h")
        assert feed.running
        base = feed.counters["refreshes"]
        feed.on_hub_frame("resources.changed")
        await asyncio.sleep(0.05)
        assert feed.counters["refreshes"] == base + 1 and env.notified == []
        env.deliver([line(NOW - 20, "b", fresh=2, write=0, read=0, out=2)], name="u")
        feed.on_hub_frame("resources.changed")
        await asyncio.sleep(0.05)
        assert env.notified == [("stats_feed", "local", 1.0)]
        await feed.stop()

    asyncio.run(go())


def test_lease_lapses_and_the_task_ends(env, monkeypatch):
    monkeypatch.setattr(feed_module, "LEASE_S", 0.4)
    monkeypatch.setattr(feed_module, "KEEPALIVE_S", 0.05)
    monkeypatch.setattr(feed_module, "REFRESH_FLOOR_S", 0.0)

    async def go():
        feed = env.feed(clock=time.monotonic)
        await feed.body("1h")
        assert feed.leased() and feed.running
        await asyncio.sleep(0.2)
        assert env.notified and all(n[0] == "stats_feed" for n in env.notified)
        await asyncio.sleep(0.4)
        assert not feed.leased() and not feed.running
        sent = len(env.notified)
        await asyncio.sleep(0.2)
        assert len(env.notified) == sent

    asyncio.run(go())

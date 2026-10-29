
from __future__ import annotations

import asyncio
import json
import time

from src.core.resource_push import bodies
from src.core.stats_feed import feed as feed_module
from src.core.stats_feed.model import WINDOWS
from tests.python.stats_feed.conftest import NOW, line


def test_push_body_is_what_each_windows_get_answers(env):
    async def go():
        env.deliver([line(NOW - 30, "a", fresh=1, write=0, read=0, out=1)])
        feed = env.feed()
        assert feed.push_body() is None
        served = {w: json.loads(await feed.body(w)) for w in WINDOWS}
        pushed = feed.push_body()
        await feed.stop()
        return served, pushed

    served, pushed = asyncio.run(go())
    assert pushed == served


def test_a_keepalive_tick_marks_its_frame_bodyless(env, monkeypatch):
    monkeypatch.setattr(feed_module, "LEASE_S", 0.4)
    monkeypatch.setattr(feed_module, "KEEPALIVE_S", 0.05)
    monkeypatch.setattr(feed_module, "REFRESH_FLOOR_S", 0.0)
    bodies._skip.clear()

    async def go():
        feed = env.feed(clock=time.monotonic)
        await feed.body("1h")
        await asyncio.sleep(0.15)
        marked = "stats_feed" in bodies._skip
        await feed.stop()
        return marked

    assert asyncio.run(go()) is True
    bodies._skip.clear()

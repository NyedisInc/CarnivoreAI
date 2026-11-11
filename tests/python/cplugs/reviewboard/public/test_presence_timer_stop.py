
from __future__ import annotations

import asyncio
from pathlib import Path

from src.cplugs.reviewboard.public import lifecycle, presence, wiring
from tests.python.cplugs.reviewboard.harness import make_env


def test_a_visitor_beat_arms_the_timer_and_bringing_public_links_down_cancels_it(tmp_path: Path) -> None:
    env = make_env(tmp_path)

    async def scenario() -> None:
        ctx = env.host.context("reviewboard", background=True)
        deps = wiring.build(ctx)
        deps.beat("a1", "20261013-bar", "visitor-key")
        handle = wiring.TIMER["at"]
        assert handle is not None and not handle.cancelled(), "a beat arms the one expiry timer"
        await lifecycle._bring_down()
        assert handle.cancelled() and wiring.TIMER["at"] is None, "the timer outlived the stop"

    try:
        asyncio.run(scenario())
    finally:
        presence.PRESENCE.__init__()


from __future__ import annotations

import asyncio
import re
from pathlib import Path

from src.core.stats_feed import feed as feed_module
from src.core.stats_feed import peers
from tests.python.stats_feed.conftest import NOW, line

ROOT = Path(__file__).resolve().parents[3]
KICKER_IMPORT = re.compile(r"stats_feed(\.|\s+import\s+.*)\bkicker\b|stats_feed\.kicker|import\s+Kicker")


def test_nothing_imports_the_kicker_and_the_module_is_gone():
    files = list((ROOT / "src").rglob("*.py"))
    assert len(files) > 500
    assert not (ROOT / "src/core/stats_feed/kicker.py").exists()
    offenders = [str(f) for f in files if KICKER_IMPORT.search(f.read_text(encoding="utf-8", errors="replace"))]
    assert offenders == []


def test_feed_has_no_kicker_and_local_answer_keeps_wire_version(env):
    async def go():
        env.deliver([line(NOW - 30, "a", fresh=1, write=0, read=0, out=1)])
        feed = env.feed()
        assert not hasattr(feed, "kicker") and "kicker" not in feed.diagnostics()
        answer = await feed.local_answer()
        assert answer["v"] == peers.WIRE_VERSION == 1 and answer["windows"]
        assert feed_module.StatsFeed is type(feed)

    asyncio.run(go())

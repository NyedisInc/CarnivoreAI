
from __future__ import annotations

import re
from pathlib import Path

from src.core.resource_push import topics

SRC = Path(__file__).resolve().parents[3] / "src"
NAMING = re.compile(r"\bSTATS_FEED\b|notify\w*\(\s*[\"']stats_feed[\"']")


def _writers(root: Path) -> list:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*.py")
                  if p.name != "topics.py" and NAMING.search(p.read_text()))


def test_advertised_and_notified_only_by_the_feed():
    assert topics.STATS_FEED in topics.RESOURCE_TOPICS and topics.STATS_FEED in topics.all_topics()
    assert _writers(SRC) == ["core/stats_feed/feed.py"]


def test_a_second_notifier_would_be_red(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "feed.py").write_text("notify_coalesced(topics.STATS_FEED, 'local', 1.0)\n")
    (tmp_path / "core" / "rogue.py").write_text("resource_push.notify('stats_feed')\n")
    assert _writers(tmp_path) == ["core/feed.py", "core/rogue.py"]

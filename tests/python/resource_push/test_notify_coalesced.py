
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict, List

from src.core import resource_push
from src.core.resource_push.notifier import ResourceNotifier
from src.core.resource_push.topics import PROJECTS, LAYOUTS


def _run(coro):
    return asyncio.run(coro)


def test_burst_sends_one_now_and_one_trailing_and_other_topics_are_immediate() -> None:
    async def scenario() -> List[Dict[str, Any]]:
        frames: List[Dict[str, Any]] = []
        notifier = ResourceNotifier(lambda f: frames.append(f) or 1, asyncio.get_running_loop(),
                                    window_seconds=0.0)
        for _ in range(20):
            notifier.notify_coalesced(PROJECTS, "cloude_a", 0.3)
        await asyncio.sleep(0.05)
        assert [f["topics"] for f in frames] == [[PROJECTS]], "first stamp must go out at once"
        notifier.notify(LAYOUTS)
        await asyncio.sleep(0.05)
        assert frames[-1]["topics"] == [LAYOUTS]
        await asyncio.sleep(0.4)
        assert [f["topics"] for f in frames if PROJECTS in f["topics"]] == [[PROJECTS]] * 2, (
            "the suppressed 19 must land as exactly one trailing notice")
        await asyncio.sleep(0.5)
        assert len([f for f in frames if PROJECTS in f["topics"]]) == 2, "no timer at idle"
        notifier.close()
        return frames

    _run(scenario())


def test_work_stamp_path_coalesces(monkeypatch) -> None:
    from src.core import session_work_stamp as sws

    async def scenario() -> int:
        frames: List[Dict[str, Any]] = []
        notifier = ResourceNotifier(lambda f: frames.append(f) or 1, asyncio.get_running_loop(),
                                    window_seconds=0.0)
        resource_push.notifier._active = notifier
        counter = {"n": 0}

        def fake_stamp(*a, **k):
            counter["n"] += 1
            return "exact_epoch"

        monkeypatch.setattr(sws, "stamp_work", fake_stamp)
        monkeypatch.setattr(sws, "PROJECTS_NOTIFY_MIN_INTERVAL_SECONDS", 60.0)
        for _ in range(10):
            conn = sqlite3.connect(":memory:")
            sws.persist_instance_stamp(lambda: conn, "ses_1", "cloude_a",
                                       tmux_socket="cloude", tmux_created_epoch=1)
        await asyncio.sleep(0.05)
        notifier.close()
        resource_push.notifier._active = None
        assert counter["n"] == 10
        return len([f for f in frames if PROJECTS in f["topics"]])

    assert _run(scenario()) == 1

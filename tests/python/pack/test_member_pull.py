
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.core.pack.rollup_import import member_pull


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(member_pull, "_PAIRS", [])
    monkeypatch.setattr(member_pull, "_TASKS", {})
    monkeypatch.setattr(member_pull, "_WAKE", None)
    monkeypatch.setattr(member_pull, "_LAST", {})


def _importer(log: List[str], block: dict) -> Any:
    async def maybe_pull_member(iid: str, post: Any) -> None:
        if iid == "slow":
            try:
                await block["event"].wait()
            except asyncio.CancelledError:
                log.append("slow-cancelled")
                raise
        log.append(iid)
    return SimpleNamespace(maybe_pull_member=maybe_pull_member)


def test_first_wake_is_kept_one_slow_member_blocks_no_other_and_shutdown_awaits_every_pull(monkeypatch):
    monkeypatch.setattr(member_pull.exchange, "bulk_post_via", lambda client, **kw: None)
    monkeypatch.setattr(member_pull, "paced", lambda iid, post: post)
    log: List[str] = []

    async def scenario() -> None:
        block = {"event": asyncio.Event()}
        member_pull._PAIRS[:] = [("slow", object()), ("fast", object())]
        task = asyncio.create_task(member_pull.run(_importer(log, block)))
        for _ in range(50):
            await asyncio.sleep(0)
            if "fast" in log:
                break
        assert "fast" in log and "slow" not in log
        slow = member_pull._TASKS["slow"]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert slow.cancelled() and "slow-cancelled" in log and member_pull._TASKS == {}

    asyncio.run(scenario())

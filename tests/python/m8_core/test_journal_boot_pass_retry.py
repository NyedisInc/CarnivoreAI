from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, List

import pytest

from src.core import session_journal_task as task


@pytest.mark.asyncio
async def test_boot_pass_is_retried_then_observe_takes_over(tmp_path: Path, monkeypatch) -> None:
    calls: List[str] = []

    def boot(*_a: Any) -> dict:
        calls.append("boot")
        if calls.count("boot") < 3:
            raise OSError("tmux gone for a moment")
        return {"boot_change": "rebooted"}

    def observe(*_a: Any) -> dict:
        calls.append("observe")
        return {}

    monkeypatch.setattr(task, "boot_pass", boot)
    monkeypatch.setattr(task, "observe_pass", observe)
    monkeypatch.setenv(task.ENABLE_ENV, "1")
    sched = task.SessionJournalScheduler(tmp_path, object(), "cloude", tmp_path / "db")
    sched.interval = 0.01
    assert sched.start()
    for _ in range(100):
        if "observe" in calls:
            break
        await asyncio.sleep(0.01)
    await sched.aclose()
    assert calls[:3] == ["boot", "boot", "boot"]
    assert sched.boot_summary == {"boot_change": "rebooted"}


@pytest.mark.asyncio
async def test_a_boot_pass_that_keeps_crashing_stops_after_the_bound(tmp_path: Path, monkeypatch) -> None:
    calls: List[str] = []

    def boot(*_a: Any) -> dict:
        calls.append("boot")
        raise OSError("always")

    monkeypatch.setattr(task, "boot_pass", boot)
    monkeypatch.setattr(task, "observe_pass", lambda *_a: calls.append("observe") or {})
    monkeypatch.setenv(task.ENABLE_ENV, "1")
    sched = task.SessionJournalScheduler(tmp_path, object(), "cloude", tmp_path / "db")
    sched.interval = 0.01
    sched.start()
    for _ in range(100):
        if "observe" in calls:
            break
        await asyncio.sleep(0.01)
    await sched.aclose()
    assert calls.count("boot") == task.BOOT_PASS_ATTEMPTS

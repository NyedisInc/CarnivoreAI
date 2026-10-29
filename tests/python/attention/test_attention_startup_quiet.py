from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from src.core.attention.startup_quiet import STARTUP_QUIET_WINDOW_SECONDS, StartupQuiet
from tests.test_attention_pipeline import SID, Pipeline
from tests.test_attention_wiring import no_real_pulls  # noqa: F401

WORKING = "working (2s · esc to interrupt)"
REST = "Ask Codex to do anything"


def _finish_turn(run: Pipeline) -> None:
    run.codex("inProgress")
    run.screen = WORKING
    run.tick()
    run.codex("completed")
    run.screen = REST
    for _ in range(4):
        run.tick()


def test_restart_startup_turn_is_quiet_and_a_later_real_turn_still_alerts(
    tmp_path, monkeypatch, no_real_pulls  # noqa: F811
):
    run = Pipeline(tmp_path, monkeypatch, "codex")
    run.codex("completed")
    run.tick()
    run.watcher.invalidate_session(SID)
    _finish_turn(run)
    assert run.manager.unread_writes == [], "startup turn must set no unread"
    assert run.manager.toasts == [], "startup turn must raise no finished toast"
    _finish_turn(run)
    assert run.manager.unread_writes, "a real turn must still set unread"
    assert run.manager.toasts, "a real turn must still raise a toast"


def test_quiet_period_expires_and_swallows_only_once():
    quiet = StartupQuiet()
    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    quiet.arm("a", now)
    assert quiet.swallows_done("a", now + timedelta(seconds=5)) is True
    assert quiet.swallows_done("a", now + timedelta(seconds=6)) is False
    quiet.arm("b", now)
    late = now + timedelta(seconds=STARTUP_QUIET_WINDOW_SECONDS + 1)
    assert quiet.swallows_done("b", late) is False


def test_the_guard_survives_the_restart_window_with_the_target_unlisted(
    tmp_path, monkeypatch, no_real_pulls  # noqa: F811
):
    run = Pipeline(tmp_path, monkeypatch, "codex")
    run.codex("completed")
    run.tick()
    run.watcher.invalidate_session(SID)
    listed = run.watcher._list_targets
    run.watcher._list_targets = lambda: []
    run.now += timedelta(seconds=2)
    asyncio.run(run.watcher.tick_once())
    run.watcher._list_targets = listed
    _finish_turn(run)
    assert run.manager.toasts == [], "the startup turn after a restart must stay quiet"
    assert run.manager.unread_writes == []


def test_retain_only_keeps_an_unlisted_guard_until_its_window_ends():
    quiet = StartupQuiet()
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    quiet.arm("restarting", now)
    quiet.retain_only(set(), now + timedelta(seconds=1))
    assert quiet.is_armed("restarting") is True
    quiet.retain_only(set(), now + timedelta(seconds=STARTUP_QUIET_WINDOW_SECONDS + 1))
    assert quiet.is_armed("restarting") is False

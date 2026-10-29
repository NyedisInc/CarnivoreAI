
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_t9w_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_t9w_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import ttl_flight
from src.core.attention.listing_marks import marks_stamp
from src.core.listing_push import publisher as publisher_module
from src.core.listing_push.publisher import Collection, CollectionResult, ListingPublisher
from src.core.sessions import pane_listing_cache
from src.core.tmux_control import changes


async def _passes(feed, seconds: float) -> int:
    built = []

    async def build(_ctx):
        built.append(1)
        return CollectionResult(rows=[])

    pub = ListingPublisher([Collection("c", build, lambda r: r.get("n"))], lambda frame: 0, lambda: 1,
                           backstop_seconds=0.2, min_interval=0.05, feed=feed)
    task = asyncio.create_task(pub.run())
    await asyncio.sleep(seconds)
    task.cancel()
    return len(built)


@pytest.mark.asyncio
async def test_a_live_feed_stretches_the_backstop_and_a_dead_one_does_not(monkeypatch):
    monkeypatch.setattr(publisher_module, "EVENT_BACKSTOP_SECONDS", 30.0)

    async def live():
        return True

    async def dead():
        return False

    assert await _passes(live, 1.2) <= 1, "a live feed must stretch the backstop"
    assert await _passes(dead, 1.2) >= 3, "no feed keeps the fast backstop"


@pytest.mark.asyncio
async def test_a_remote_host_session_keeps_the_fast_backstop(monkeypatch):
    monkeypatch.setenv("CARNIVORE_CONTROL_INPUT", "1")
    called = []

    async def listen():
        called.append(1)
        return True

    from src.core.tmux_control import client

    monkeypatch.setattr(client, "get_control_input", lambda sock: SimpleNamespace(listen=listen))
    assert await changes.control_feed(lambda: "s", lambda: True)() is True
    assert await changes.control_feed(lambda: "s", lambda: False)() is False
    assert len(called) == 1, "a remote host must not even start the control client's stretch"


@pytest.mark.asyncio
async def test_wake_listener_drops_the_owner_listing_cache_and_the_pane_cache_then_wakes():
    cache = ttl_flight.TtlFlight("t9_wake_test", 60.0)
    calls = []

    async def work():
        calls.append(1)
        return list(calls)

    await cache.get(work)
    await cache.get(work)
    assert len(calls) == 1
    dropped = []
    real = pane_listing_cache.invalidate_pane_listing
    pane_listing_cache.invalidate_pane_listing = lambda sock=None: dropped.append(sock)
    woke = []
    try:
        changes.wake_listener(lambda: woke.append(1))("sock")
    finally:
        pane_listing_cache.invalidate_pane_listing = real
    assert dropped == ["sock"] and woke == [1]
    await cache.get(work)
    assert len(calls) == 2, "the 1 s owner-listing cache must be dropped so the wake pass sees the new session"


def test_main_wires_the_feed_the_listener_and_the_remote_guard():
    main = (ROOT / "src" / "core" / "boot" / "attention.py").read_text()
    assert "feed=tmux_changes.control_feed(" in main
    assert "is_remote_backend(b)" in main
    assert "tmux_changes.add_listener(tmux_changes.wake_listener(listing_publisher.wake))" in main


def _watcher_pass(monkeypatch):
    from unittest.mock import MagicMock

    from src.core.attention import wiring_builders

    monkeypatch.setattr(wiring_builders, "to_display", lambda *a, **k: "idle")
    monkeypatch.setattr(wiring_builders.session_change_notice, "publish_attention_status", lambda *a, **k: None)
    woke: list = []
    app_state = SimpleNamespace(listing_publisher=SimpleNamespace(wake=lambda: woke.append(1)))
    manager = SimpleNamespace(_registry=SimpleNamespace(sessions={"s": 1}), _is_unread=lambda *a: False)
    effects = MagicMock()
    effects.instance_for.return_value = (None, None)
    hooks = wiring_builders.ObservationHooks(*(MagicMock() for _ in range(7)))
    on_observation = wiring_builders.make_on_observation(manager, app_state, effects, hooks, None)
    target = SimpleNamespace(session_id="s", key="k")

    def feed(evidence):
        verdict = SimpleNamespace(state="idle", reason="r", tier=0, activity_hint=None)
        on_observation(target, SimpleNamespace(evidence=evidence, verdict=verdict, stale=False, observed_at=0))

    return feed, woke


def _evidence(**over):
    base = dict(subagents=None, timers=None, skills=None, parked_work=None, background_open=None,
                transcript=SimpleNamespace(mcp_events=(), verdict="unread"), registry=SimpleNamespace(known=False), agent_family="claude")
    return SimpleNamespace(**{**base, **over})


def test_the_watcher_wakes_only_when_a_wire_mark_moves(monkeypatch):
    from datetime import datetime, timezone

    feed, woke = _watcher_pass(monkeypatch)

    def tally(running, at):
        return SimpleNamespace(state="measured", running=running, total=3, unknown=0, last_activity_at=at)

    t0, t1 = datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)
    feed(_evidence(subagents=tally(1, t0)))
    assert woke == [], "the first observation of a session has nothing to compare against"
    feed(_evidence(subagents=tally(1, t0)))
    assert woke == [], "the same stamp must not wake"
    feed(_evidence(subagents=tally(1, t1)))
    assert woke == [], "last_activity_at is not on the wire: it must not wake"
    feed(_evidence(subagents=tally(2, t1)))
    assert woke == [1], "a changed wire field (running) must wake"


def test_marks_stamp_moves_with_each_listing_mark():
    first = marks_stamp(_evidence())
    assert marks_stamp(_evidence()) == first
    ns = SimpleNamespace
    for field, value in (("subagents", ns(state="measured", running=2, total=2)),
                         ("timers", ns(state="measured", live=1, next_fire_at="t")),
                         ("skills", ns(state="measured", fired=3, last_skill="x", last_at="t")),
                         ("parked_work", ns(is_live=True, entries=("e",))), ("background_open", 1)):
        assert marks_stamp(_evidence(**{field: value})) != first, field
    assert marks_stamp(_evidence(transcript=ns(mcp_events=("down",), verdict="unread"))) != first


def test_marks_stamp_ignores_fields_the_wire_drops():
    from datetime import datetime, timezone

    def sub(**over):
        return SimpleNamespace(**{**dict(state="measured", running=1, total=2, unknown=0,
                                         last_activity_at=datetime(2026, 1, 1, tzinfo=timezone.utc)), **over})

    base = marks_stamp(_evidence(subagents=sub()))
    assert marks_stamp(_evidence(subagents=sub(last_activity_at=datetime(2026, 2, 1, tzinfo=timezone.utc), unknown=5))) == base
    assert marks_stamp(_evidence(subagents=sub(total=3))) != base

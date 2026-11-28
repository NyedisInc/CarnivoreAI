
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

# ruff: noqa: E402
from src.core.attention.transcript_walk import WindowWalk
from src.core.auto_sleep.idle_seed_paths import resolve_claude_seed
from src.core.attention.registry_record import REG_OK
from tests.test_auto_sleep_sleeper import NOW, _add, _config, _run, world  # noqa: F401

T0 = datetime(2026, 11, 19, 23, 11, tzinfo=timezone.utc)


def test_bookkeeping_records_never_move_the_newest_activity():
    walk = WindowWalk()
    walk.feed({"type": "assistant", "timestamp": T0.isoformat().replace("+00:00", "Z"), "message": {"content": []}})
    for kind in ("custom-title", "cost-state", "agent-name", "attachment", "queue-operation"):
        walk.feed({"type": kind, "timestamp": (T0 + timedelta(minutes=60)).isoformat().replace("+00:00", "Z")})
    assert walk.newest_activity_at == T0
    assert walk.newest_append_at > T0


def test_seed_uses_activity_and_the_registry_status_time_never_a_file_mtime(tmp_path):
    reg = SimpleNamespace(verdict=REG_OK, pid=1, started_at=None, status_updated_at=T0)
    candidates, _ = resolve_claude_seed(
        registry=reg, cwd=None, claude_session_uuid="u", tmux_name="t", session_started_epoch=None,
        config_path=tmp_path / "config.json", activity_at=T0)
    assert {when for when, _ in candidates} == {T0}


@pytest.mark.parametrize(("kwargs", "code"), [
    ({"idle_minutes": 12}, "idle_waiting"), ({"family": "terminal"}, "not_agent"), ({"status": "question"}, "not_idle"),
    ({"hint": "shell"}, "shell_running"), ({"observed": False}, "status_unmeasured"), ({"listening": True}, "listening"),
    ({"conv": None}, "no_conversation"),
])
def test_each_rule_leaves_its_verdict(world, kwargs, code):
    sid, _ = _add(world, **kwargs)
    _run(world)
    assert world.sleeper.verdict_for(sid).code == code


def test_viewer_keep_awake_and_unmeasured_ports_leave_their_verdicts(world):
    a, _ = _add(world, n=1)
    world.manager._registry.subscribers[a] = [object()]
    b, uuid_b = _add(world, n=2)
    c, _ = _add(world, n=3)
    world.sleeper._take_listeners = lambda: (_ for _ in ()).throw(__import__("src.core.conversation_writers", fromlist=["x"]).MeasureError("no table"))
    _config(world, auto_sleep={"enabled": True, "keep_awake": [uuid_b]})
    _run(world)
    assert world.sleeper.verdict_for(a).code == "open_in_window"
    assert world.sleeper.verdict_for(b).code == "keep_awake_list"
    assert world.sleeper.verdict_for(c).code == "ports_unmeasured"


def test_the_verdict_carries_the_clock_start_and_threshold_and_nothing_that_ticks(world):
    sid, _ = _add(world, idle_minutes=12)
    _run(world)
    first = world.sleeper.verdict_for(sid)
    assert first.idle_since == NOW - timedelta(minutes=12) and first.threshold_minutes == 60
    world.sleeper._now = lambda: NOW + timedelta(minutes=5)
    asyncio.run(world.sleeper.pass_once())
    assert world.sleeper.verdict_for(sid) == first


def test_the_listing_stamp_copies_the_verdict_for_agents_only(world):
    from src.api import sleep_hold_listing
    from src.models import SessionInfo

    sid, _ = _add(world)
    _run(world)
    info = SessionInfo.model_construct(session=SimpleNamespace(id=sid), agent_family="claude", sleep_hold=None, sleep_verdict=None)
    sleep_hold_listing.mark_sleep_hold(world.manager, [info], world.sleeper)
    assert info.sleep_verdict.code == "due"

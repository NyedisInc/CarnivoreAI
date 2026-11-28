
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from src.config.provider_account_switch import ProviderAccountSwitchConfig
from src.config.provider_accounts import ProviderAccount
from src.core.account_switch import agy_rotate
from src.core.account_switch.rotate_state import RotationState
from src.models.provider_ledger import AccountUsage, LedgerSnapshot, LedgerTotal, LoopStatus, UsageWindow

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def row(account_id, short=10.0, week=10.0, state="ok"):
    windows = [UsageWindow(kind="gemini-5h", label="5h", used_pct=short, window_seconds=18000, resets_at=NOW + timedelta(hours=2)),
               UsageWindow(kind="gemini-weekly", label="7d", used_pct=week, window_seconds=604800, resets_at=NOW + timedelta(days=3))]
    return AccountUsage(id=account_id, name=account_id, provider="antigravity", credential_state=state, windows=windows)


def info(name, status="idle"):
    return SimpleNamespace(tmux_session=name, activity_status=status, activity_hint=None, session=SimpleNamespace(id="ses_" + name))


class FakeManager:
    def __init__(self):
        self.respawned = []

    async def list_session_infos(self):
        return []

    async def respawn_session(self, name, **kwargs):
        self.respawned.append((name, kwargs))
        return {"ok": True, "kind": "agent"}


def test_pick_target_takes_the_best_other_account_with_a_copy():
    rows = [row("a", short=100), row("b", short=30), row("c", short=10)]
    assert agy_rotate.pick_target(rows, capped_id="a", threshold=99, now=NOW, has_copy=lambda i: True) in ("b", "c")
    assert agy_rotate.pick_target(rows, capped_id="a", threshold=99, now=NOW, has_copy=lambda i: i == "b") == "b"
    assert agy_rotate.pick_target(rows, capped_id="a", threshold=99, now=NOW, has_copy=lambda i: False) is None
    assert agy_rotate.pick_target([row("a"), row("b", state="missing")], capped_id="a", threshold=99, now=NOW) is None


def run_rotate(monkeypatch, tmp_path, sessions, rows, *, copy_ok=True):
    manager = FakeManager()
    swaps = []
    monkeypatch.setattr(agy_rotate, "_STATE", RotationState(path=tmp_path / "rot.json", clock=lambda: NOW.timestamp()))
    monkeypatch.setattr(agy_rotate, "live_agy_sessions", lambda *a, **k: sessions)
    monkeypatch.setattr(agy_rotate.agy_accounts, "has_copy", lambda i: copy_ok)
    monkeypatch.setattr(agy_rotate, "activate_account", lambda path, target, state_dir=None: swaps.append(target))
    monkeypatch.setattr(agy_rotate.auto_switch, "record_switch", lambda *a, **k: {})

    class FakeRotation:
        def __init__(self, *a, **k):
            pass

        async def wait_ready(self, session_id):
            return False

    monkeypatch.setattr(agy_rotate.limit_rotate, "Rotation", FakeRotation)
    snapshot = LedgerSnapshot(accounts=rows, total=LedgerTotal(accounts=len(rows)), loop=LoopStatus(alive=True, last_pass_at=NOW))
    accounts = [ProviderAccount(id=r.id, name=r.id, provider="antigravity") for r in rows]
    switch = ProviderAccountSwitchConfig(auto_switch=True, active_antigravity="a")
    restarted = asyncio.run(agy_rotate.rotate(manager, SimpleNamespace(), snapshot, accounts, switch, config_path=tmp_path / "c.json",
                                              state_dir=tmp_path, now=NOW, parents={}, commands={}))
    return restarted, swaps, manager


EXHAUSTED = {"quota": {"gemini-5h": {"remaining_fraction": 0}}}


def test_limit_swaps_then_restarts_the_limited_and_the_idle_but_not_the_working(monkeypatch, tmp_path):
    sessions = [(info("limited", "unknown"), EXHAUSTED), (info("idle"), {"quota": {}}), (info("busy", "working"), {"quota": {}})]
    restarted, swaps, manager = run_rotate(monkeypatch, tmp_path, sessions, [row("a", short=100), row("b")])
    assert swaps == ["b"] and sorted(restarted) == ["idle", "limited"]
    assert all(kw["live_restart_confirmed"] and kw["require_agent_resume"] for _, kw in manager.respawned)


def test_no_exhausted_quota_means_nothing_happens(monkeypatch, tmp_path):
    restarted, swaps, manager = run_rotate(monkeypatch, tmp_path, [(info("idle"), {"quota": {"gemini-5h": {"remaining_fraction": 0.4}}})], [row("a"), row("b")])
    assert restarted == [] and swaps == [] and manager.respawned == []


def test_no_account_with_headroom_leaves_everything_alone(monkeypatch, tmp_path):
    restarted, swaps, manager = run_rotate(monkeypatch, tmp_path, [(info("limited", "unknown"), EXHAUSTED)], [row("a", short=100)])
    assert restarted == [] and swaps == [] and manager.respawned == []


def test_a_second_pass_in_the_same_block_is_bounded_by_the_attempt_cap(monkeypatch, tmp_path):
    sessions = [(info("limited", "unknown"), EXHAUSTED)]
    first = run_rotate(monkeypatch, tmp_path, sessions, [row("a", short=100), row("b")])
    assert first[1] == ["b"]
    second = run_rotate(monkeypatch, tmp_path, sessions, [row("a", short=100), row("b")])
    assert second[1] == []

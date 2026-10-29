
from __future__ import annotations

import ast
import asyncio
import builtins
import io
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import src.core.account_switch.auto_switch as auto_switch_module
from src.config import settings
from src.config.provider_accounts import ProviderAccount, managed_dir_for
from src.core.account_switch import auto_switch, launch_env, shared_links, store
from src.core.provider_ledger import accounts_store, managed_profiles
from src.models.provider_ledger import (
    AccountUsage,
    LedgerSnapshot,
    LedgerTotal,
    LoopStatus,
    UsageWindow,
)
from src.models.websocket import WSMessageType
from tests.helpers.claude_profile import write_claude_profile

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def usage(account_id: str, pct: float, provider: str = "claude", state: str = "ok") -> AccountUsage:
    return AccountUsage(
        id=account_id, name=account_id, provider=provider, credential_state=state,
        windows=[UsageWindow(kind="five_hour", label="5h", used_pct=pct,
                             window_seconds=18000, resets_at=NOW + timedelta(hours=1))],
    )


def snapshot(*rows: AccountUsage) -> LedgerSnapshot:
    return LedgerSnapshot(accounts=list(rows), total=LedgerTotal(accounts=len(rows)),
                          loop=LoopStatus(alive=True))


@pytest.fixture()
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {}}))
    for account_id in ("a", "b"):
        managed_profiles.ensure_managed_dir(account_id)
        write_claude_profile(managed_dir_for(account_id))
        accounts_store.upsert_account(path, ProviderAccount(
            id=account_id, name=account_id, provider="claude",
            claude_config_dir=managed_dir_for(account_id), managed=True,
        ))
    store.set_active(path, "claude", "a")
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    return path


class Hub:

    def __init__(self):
        self.frames = []

    def publish(self, frame):
        self.frames.append(frame)
        return 1


class AppState:

    def __init__(self):
        self.event_hub = Hub()
        self.session_manager = BoobyTrappedManager()


class BoobyTrappedManager:

    def __getattr__(self, name):
        raise AssertionError(f"auto-switch reached the session manager: {name}")


def run(snap, config, app_state=None):
    return asyncio.run(auto_switch.after_pass(
        snap, app_state, config_path=lambda: config, clock=lambda: NOW,
    ))


@pytest.fixture()
def hub_state(monkeypatch):
    state = AppState()
    from src.core import session_change_notice

    monkeypatch.setattr(session_change_notice, "get_hub", lambda s: s.event_hub if s else None)
    return state


def test_off_by_default_nothing_moves(config, hub_state):
    assert run(snapshot(usage("a", 100), usage("b", 0)), config, hub_state) == []
    assert store.read_switch(config).active_claude == "a"
    assert hub_state.event_hub.frames == []


def test_on_it_moves_the_pointer_logs_and_publishes(config, hub_state):
    store.set_auto(config, enabled=True)
    applied = run(snapshot(usage("a", 99), usage("b", 10)), config, hub_state)
    assert [(d.from_account_id, d.to_account_id) for d in applied] == [("a", "b")]
    assert store.read_switch(config).active_claude == "b"
    (frame,) = hub_state.event_hub.frames
    assert frame["type"] == WSMessageType.PROVIDER_ACCOUNT_SWITCHED
    assert (frame["from_account_id"], frame["to_account_id"], frame["reason"]) == ("a", "b", "auto")
    assert auto_switch.last_switch()["to_account_id"] == "b"


def test_below_the_default_threshold_nothing_moves_even_when_on(config, hub_state):
    store.set_auto(config, enabled=True)
    assert run(snapshot(usage("a", 98.9), usage("b", 0)), config, hub_state) == []
    assert store.read_switch(config).active_claude == "a"


def test_never_restarts_a_session_working_or_not(config, hub_state):
    store.set_auto(config, enabled=True)
    applied = run(snapshot(usage("a", 100), usage("b", 0)), config, hub_state)
    assert len(applied) == 1


def test_the_auto_switch_module_has_no_route_to_a_restart():
    source = Path(auto_switch_module.__file__).read_text()
    code_names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Name, ast.Attribute))
    }
    for forbidden in ("session_manager", "respawn", "respawn_session", "restart_session",
                      "list_session_infos", "send_keys", "kill_session"):
        assert forbidden not in code_names, forbidden



CREDENTIAL_NAMES = (".credentials.json", "auth.json")


class Recorder:

    def __init__(self):
        self.opened = []
        self.spawned = []
        self.credential_calls = []


@pytest.fixture()
def planted(config, tmp_path):
    for account_id in ("a", "b"):
        profile = Path(managed_dir_for(account_id))
        (profile / ".credentials.json").write_text('{"claudeAiOauth": {"accessToken": "x"}}')
    (tmp_path / ".codex").mkdir(exist_ok=True)
    (tmp_path / ".codex" / "auth.json").write_text('{"tokens": {}}')
    return config


@pytest.fixture()
def recorder(monkeypatch, planted):
    rec = Recorder()
    real_open = builtins.open
    real_io_open = io.open

    def spy_open(file, *args, **kwargs):
        if not isinstance(file, int):
            rec.opened.append(str(file))
        return real_open(file, *args, **kwargs)

    def spy_io_open(file, *args, **kwargs):
        if not isinstance(file, int):
            rec.opened.append(str(file))
        return real_io_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(io, "open", spy_io_open)

    real_os_open = os.open

    def spy_os_open(path, *args, **kwargs):
        rec.opened.append(str(path))
        return real_os_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_os_open)

    def refuse_spawn(*args, **kwargs):
        rec.spawned.append(args)
        raise AssertionError("the switch spawned a process")

    monkeypatch.setattr(subprocess, "run", refuse_spawn)
    monkeypatch.setattr(subprocess, "Popen", refuse_spawn)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse_spawn)

    from src.core.provider_ledger import codex_credentials, credentials, keychain

    for module in (keychain, credentials, codex_credentials):
        for name in dir(module):
            if name.startswith("read_") or name in ("find_generic_password",):
                attr = getattr(module, name)
                if callable(attr):
                    def trap(*a, _name=f"{module.__name__}.{name}", **k):
                        rec.credential_calls.append(_name)
                        raise AssertionError(f"the switch read a credential: {_name}")

                    monkeypatch.setattr(module, name, trap)
    return rec


def test_no_token_is_read_or_written_by_a_switch(config, hub_state, recorder, tmp_path):
    store.set_active(config, "claude", "b")
    launch_env.account_env(config)
    store.set_auto(config, enabled=True)
    run(snapshot(usage("b", 100), usage("a", 1)), config, hub_state)
    shared_links.ensure_shared_links(managed_dir_for("a"), "claude", managed=True)

    touched = [p for p in recorder.opened if p.endswith(CREDENTIAL_NAMES)]
    assert touched == []
    assert recorder.credential_calls == []
    assert recorder.spawned == []
    for path in recorder.opened:
        name = os.path.basename(path)
        assert name.startswith("config.json") or name.startswith(".config.json") or name == ".claude.json", path
    assert recorder.opened, "the recorder saw nothing, so it proved nothing"
    for account_id in ("a", "b"):
        body = (Path(managed_dir_for(account_id)) / ".credentials.json").read_text()
        assert body == '{"claudeAiOauth": {"accessToken": "x"}}'




def test_a_manual_choice_made_while_the_plan_ran_wins(config, hub_state, monkeypatch):
    store.set_auto(config, enabled=True)
    real_plan = auto_switch.plan_switches

    def plan_then_user_switches(*args, **kwargs):
        decisions = real_plan(*args, **kwargs)
        store.set_active(config, "claude", "c")
        return decisions

    monkeypatch.setattr(auto_switch, "plan_switches", plan_then_user_switches)
    applied = run(snapshot(usage("a", 100), usage("b", 0)), config, hub_state)
    assert applied == []
    assert hub_state.event_hub.frames == []
    assert store.read_switch(config).active_claude == "c"


def test_turning_it_off_while_the_plan_ran_wins(config, hub_state, monkeypatch):
    store.set_auto(config, enabled=True)
    real_plan = auto_switch.plan_switches

    def plan_then_off(*args, **kwargs):
        decisions = real_plan(*args, **kwargs)
        store.set_auto(config, enabled=False)
        return decisions

    monkeypatch.setattr(auto_switch, "plan_switches", plan_then_off)
    assert run(snapshot(usage("a", 100), usage("b", 0)), config, hub_state) == []
    assert store.read_switch(config).active_claude == "a"


def test_a_hand_edited_invalid_block_is_never_overwritten(config):
    data = json.loads(config.read_text())
    data["provider_account_switch"] = {"active_claude": "a", "threshold_percent": 40}
    config.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        store.set_auto(config, enabled=True)
    assert json.loads(config.read_text())["provider_account_switch"]["active_claude"] == "a"

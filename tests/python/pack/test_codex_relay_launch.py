
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from src.core.account_switch import auto_switch, launch_env, restart_account, session_pin, store
from src.core.account_switch.active import AUTO_SWITCH_PROVIDERS, PROVIDERS
from src.core.attention import codex_pane_home as cph
from src.core.pack.relay import codex_target
from src.core.provider_ledger import poller_scan, relay_accounts

CODEX = "0123456789ab-work-relay-codex"
CLAUDE = "0123456789ab-acme-relay"
OVERRIDES = ("CODEX_REFRESH_TOKEN_URL_OVERRIDE", "CODEX_REVOKE_TOKEN_URL_OVERRIDE")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    accounts = tmp_path / ".carnivore" / "accounts"
    monkeypatch.setenv("CARNIVORE_ACCOUNTS_DIR", str(accounts))
    (accounts / CODEX).mkdir(parents=True)
    (accounts / CLAUDE).mkdir(parents=True)
    (accounts / CLAUDE / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True}))
    config = tmp_path / "config.json"
    config.write_text("{}")
    cph.clear_cache()
    return accounts / CODEX, config


def test_codex_provider_is_switchable_but_never_auto_switched():
    assert "codex" in PROVIDERS and AUTO_SWITCH_PROVIDERS == ("claude",)


def test_relayed_codex_account_is_listed_and_launchable_only_for_codex(home):
    _home, config = home
    assert [a.id for a in session_pin.launchable_accounts(config, "codex")] == [CODEX]
    assert CODEX not in [a.id for a in session_pin.launchable_accounts(config)]
    assert CODEX in [a.id for a in poller_scan.with_auto_default([])]
    assert CODEX not in [a.id for a in poller_scan.with_auto_default([], include_relay=False)]
    with pytest.raises(session_pin.PinError):
        session_pin.require_launchable(config, CODEX)
    assert session_pin.require_launchable(config, CODEX, "codex").id == CODEX


def test_a_missing_home_or_local_codex_account_is_not_launchable(home):
    codex_home, config = home
    codex_home.rmdir()
    assert session_pin.launchable_accounts(config, "codex") == []


def test_session_account_launch_env_comes_from_codex_relay_env(home):
    codex_home, config = home
    env = launch_env.account_env(config, claude_account=CODEX, family="codex")
    assert env == codex_target.codex_relay_env(str(codex_home))
    assert all(env[name] for name in OVERRIDES) and env["CODEX_HOME"] == str(codex_home)


def test_global_codex_pointer_launches_on_the_relay_and_leaves_claude_alone(home):
    codex_home, config = home
    store.set_active(config, "codex", CODEX)
    assert launch_env.account_env(config, family="codex") == codex_target.codex_relay_env(str(codex_home))
    assert launch_env.account_env(config) == {}


def test_stale_codex_pointer_removes_all_three_variables(home):
    _home, config = home
    store.set_active(config, "codex", "0123456789ab-gone-relay-codex")
    env = launch_env.account_env(config, family="codex")
    assert env == {"CODEX_HOME": None, **dict.fromkeys(OVERRIDES)}


def test_respawn_off_a_relay_scrubs_codex_env_but_keeps_a_named_value(home, monkeypatch):
    _home, config = home
    monkeypatch.setattr(launch_env, "_config_path", lambda: config)
    scrubbed = asyncio.run(launch_env.respawn_pane_env({"A": "1"}, family="codex"))
    assert scrubbed["CODEX_HOME"] is None and all(scrubbed[n] is None for n in OVERRIDES)
    kept = asyncio.run(launch_env.respawn_pane_env({"CODEX_HOME": "/mine"}, family="codex"))
    assert kept["CODEX_HOME"] == "/mine"
    claude = asyncio.run(launch_env.respawn_pane_env({"A": "1"}))
    assert "CODEX_HOME" not in claude


def test_restart_plan_picks_the_relay_for_a_codex_session_only(home):
    _home, config = home
    plan = restart_account._resolve_blocking(config, "u1", "codex", CODEX, True)
    assert plan.account_id == CODEX and plan.chosen
    with pytest.raises(session_pin.PinError):
        restart_account._resolve_blocking(config, "u1", "claude", CODEX, False)
    session_pin.apply_choice(config, "u2", CODEX, pinned=True)
    assert restart_account._resolve_blocking(config, "u2", "claude", None, False).account_id is None
    assert restart_account._resolve_blocking(config, "u2", "codex", None, False).account_id == CODEX


def test_auto_switch_never_moves_a_codex_pointer(home):
    _home, config = home
    assert "codex" not in AUTO_SWITCH_PROVIDERS and auto_switch.AUTO_SWITCH_PROVIDERS == ("claude",)


def test_launch_record_names_the_relay_account(home, monkeypatch):
    from src.core.launch_profiles import create_seam

    _home, config = home
    monkeypatch.setattr(launch_env, "_config_path", lambda: config)
    assert create_seam.recorded_account_id("codex", CODEX) == CODEX
    store.set_active(config, "codex", CODEX)
    assert create_seam.recorded_account_id("codex", None) == CODEX


def test_a_gone_session_resolves_the_home_from_its_launch_record(home, monkeypatch, tmp_path):
    codex_home, _config = home
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE sessions (tmux_name TEXT, tmux_socket TEXT, launch_record TEXT)")
    conn.execute("INSERT INTO sessions VALUES ('carnivore_x', 'cloude', ?)", (json.dumps({"account": {"mode": "x", "id": CODEX}}),))
    conn.execute("INSERT INTO sessions VALUES ('carnivore_y', 'cloude', ?)", (json.dumps({"account": {"id": CLAUDE}}),))
    conn.commit()
    monkeypatch.setattr("src.core.db.db_path_for", lambda _d: db)
    monkeypatch.setattr("src.core.db.connect", lambda p, create=False: conn)
    monkeypatch.setattr(cph, "_read_variable", lambda socket, args: None)
    assert cph.pane_codex_home("cloude", "carnivore_x") == str(codex_home)
    assert cph.pane_codex_home("cloude", "carnivore_y") == cph.DEFAULT_CODEX_HOME
    assert cph.pane_codex_home("cloude", "carnivore_nope") == cph.DEFAULT_CODEX_HOME
    cph.clear_cache()
    monkeypatch.setattr(cph, "_read_variable", lambda socket, args: ("/tmp/live-home", False))
    assert cph.pane_codex_home("cloude", "carnivore_x") == "/tmp/live-home"


def test_the_launch_picker_lists_the_relayed_codex_login_tagged_by_provider(home, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import restart_account_routes
    from src.api.auth import require_auth

    _home, config = home
    store.set_active(config, "codex", CODEX)
    monkeypatch.setattr(restart_account_routes, "_config_path", lambda: config)
    app = FastAPI()
    app.include_router(restart_account_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    body = TestClient(app).get("/api/v1/launch/accounts").json()
    assert [(o["id"], o["provider"]) for o in body["options"] if o["provider"] == "codex"] == [(CODEX, "codex")]
    assert CLAUDE in [o["id"] for o in body["options"] if o["provider"] == "claude"]
    assert body["selected_by_provider"]["codex"] == CODEX


from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core import config_writer
from src.core.account_switch import launch_env, profile_setup, session_pin, store
from src.core.pack.move import account as move_account
from src.core.provider_ledger import credentials, poller_core, poller_scan, relay_accounts

NAME = "0123456789ab-acme-relay"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    accounts = tmp_path / ".carnivore" / "accounts"
    monkeypatch.setenv("CARNIVORE_ACCOUNTS_DIR", str(accounts))
    profile = accounts / NAME
    profile.mkdir(parents=True)
    (profile / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True}))
    config = tmp_path / "config.json"
    config.write_text("{}")
    return profile, config


def _credential(expires_in: timedelta) -> credentials.ClaudeCredential:
    return credentials.ClaudeCredential(
        access_token="t" * 30, expires_at=datetime.now(timezone.utc) + expires_in, refresh_token_expires_at=None,
        scopes=("user:inference", "user:profile"), subscription_type="max", rate_limit_tier=None, source="keychain")


def test_relay_profile_is_a_relayed_row_with_the_copys_expiry(home, monkeypatch):
    monkeypatch.setattr(credentials, "read_claude_credential", lambda _d: _credential(timedelta(hours=3)))
    rows = relay_accounts.relay_rows()
    assert [r.id for r in rows] == [NAME]
    row = rows[0]
    assert row.relayed and row.credential_state == "ok" and row.setup_complete and row.windows == []
    assert row.relay_expires_at is not None and row.plan == "max"
    monkeypatch.setattr(credentials, "read_claude_credential", lambda _d: _credential(timedelta(hours=-1)))
    assert relay_accounts.relay_rows()[0].credential_state == "expired"


def test_default_pointer_launches_on_the_relay_profile(home):
    profile, config = home
    store.set_active(config, "claude", NAME)
    env = launch_env.account_env(config)
    assert env == {"CLAUDE_CONFIG_DIR": str(profile)}
    assert [a.id for a in session_pin.launchable_accounts(config)].count(NAME) == 1
    assert move_account.launch_for("acme", None, config)["extra_env"] == {"CLAUDE_CONFIG_DIR": str(profile)}


def test_a_session_account_resolves_to_the_relay_profile(home):
    profile, config = home
    assert launch_env.account_env(config, claude_account=NAME) == {"CLAUDE_CONFIG_DIR": str(profile)}


def test_relay_profile_without_the_setup_flag_is_not_launchable(home):
    profile, config = home
    (profile / ".claude.json").write_text("{}")
    assert not profile_setup.setup_done(relay_accounts.relay_accounts()[0])
    assert NAME not in [a.id for a in session_pin.launchable_accounts(config)]


def test_the_poller_never_sees_a_relay_account(home, monkeypatch):
    _profile, config = home
    assert NAME in [a.id for a in poller_scan.with_auto_default([])]
    assert NAME not in [a.id for a in poller_scan.with_auto_default([], include_relay=False)]
    fetched = []

    async def no_fetch(*a, **k):
        fetched.append(a)
        raise AssertionError("a relay account must never be fetched or poked")

    poller = poller_core.LedgerPoller(config_path=lambda: config, claude_fetch=no_fetch,
                                      read_claude_credential=lambda _d: None, read_claude_identity=lambda _d: None)
    asyncio.run(poller_scan.read_accounts(poller._list_accounts, config))
    asyncio.run(poller.run_pass())
    assert NAME not in poller._states and not fetched


CODEX_NAME = "0123456789ab-acme-relay-codex"


def _codex_home(accounts: Path) -> Path:
    folder = accounts / CODEX_NAME
    folder.mkdir(parents=True)
    (folder / "auth.json").write_text(json.dumps({"tokens": {"access_token": "synthetic", "refresh_token": ""}}))
    return folder


def test_claude_and_codex_relay_matches_never_swallow_each_other(home):
    profile, _config = home
    _codex_home(profile.parent)
    assert [a.id for a in relay_accounts.relay_accounts()] == [NAME]
    assert relay_accounts.RELAY_NAME_RE.fullmatch(CODEX_NAME) is None
    assert relay_accounts.CODEX_RELAY_NAME_RE.fullmatch(NAME) is None
    assert [d.name for d in relay_accounts._codex_relay_dirs()] == [CODEX_NAME]
    assert relay_accounts.with_relay([]) == [*relay_accounts.relay_accounts(), *relay_accounts.codex_relay_accounts()]


def test_codex_relay_dir_is_a_relayed_codex_row_from_the_copy(home, monkeypatch):
    from src.core.provider_ledger import codex_credentials

    profile, _config = home
    folder = _codex_home(profile.parent)
    seen = []

    def read(codex_home):
        seen.append(codex_home)
        return codex_credentials.CodexCredential(
            access_token="s", id_token=None, account_id=None, plan="plus", email=None, last_refresh=None,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2), source="file")

    monkeypatch.setattr(codex_credentials, "read_codex_credential", read)
    row = next(r for r in relay_accounts.all_relay_rows() if r.provider == "codex")
    assert seen == [str(folder)]
    assert (row.id, row.name, row.relayed, row.credential_state, row.plan, row.windows) == (CODEX_NAME, "acme (relayed)", True, "ok", "plus", [])
    assert row.relay_expires_at is not None
    monkeypatch.setattr(codex_credentials, "read_codex_credential", lambda _h: None)
    assert relay_accounts.codex_relay_rows()[0].credential_state == "missing"


def test_the_poller_never_fetches_a_relay_codex_account(home, monkeypatch):
    profile, config = home
    _codex_home(profile.parent)
    fetched = []

    async def no_fetch(*a, **k):
        fetched.append(a)
        raise AssertionError("a relay codex account must never be fetched")

    poller = poller_core.LedgerPoller(config_path=lambda: config, claude_fetch=no_fetch, codex_fetch=no_fetch,
                                      read_claude_credential=lambda _d: None, read_claude_identity=lambda _d: None)
    assert CODEX_NAME in [a.id for a in poller_scan.with_auto_default([])]
    assert CODEX_NAME not in [a.id for a in poller_scan.with_auto_default([], include_relay=False)]
    asyncio.run(poller_scan.read_accounts(poller._list_accounts, config))
    asyncio.run(poller.run_pass())
    assert CODEX_NAME not in poller._states and not fetched

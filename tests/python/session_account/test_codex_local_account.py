
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.config.provider_accounts import ProviderAccount
from src.core.account_switch import codex_follow, create_account, launch_env, session_pin, store
from src.core.account_switch import restart_account
from src.core.attention import codex_pane_home as cph
from src.core.pack.relay import codex_target
from src.core.provider_ledger import accounts_store

RELAY = "0123456789ab-work-relay-codex"
LOGIN = {"tokens": {"access_token": "placeholder"}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    accounts = tmp_path / ".carnivore" / "accounts"
    accounts.mkdir(parents=True)
    monkeypatch.setenv("CARNIVORE_ACCOUNTS_DIR", str(accounts))
    default = tmp_path / ".codex"
    default.mkdir()
    monkeypatch.setattr(codex_follow, "DEFAULT_CODEX_HOME", str(default))
    monkeypatch.setattr(create_account, "_config_path", lambda: config_path)
    config = config_path = tmp_path / "config.json"
    config.write_text("{}")
    cph.clear_cache()
    return tmp_path, config


def add_local(config: Path, root: Path, name: str, *, logged_in: bool = True) -> str:
    home = root / ".carnivore" / "accounts" / name
    home.mkdir(parents=True)
    if logged_in:
        (home / "auth.json").write_text(json.dumps(LOGIN))
    accounts_store.upsert_account(config, ProviderAccount(id=name, name=name, provider="codex", codex_home=str(home), managed=True))
    return str(home)


def test_a_local_codex_account_gets_its_codex_home_and_nothing_else(world):
    root, config = world
    home = add_local(config, root, "codex")
    assert launch_env.account_env(config, claude_account="codex", family="codex") == {"CODEX_HOME": home}
    store.set_active(config, "codex", "codex")
    assert launch_env.account_env(config, family="codex") == {"CODEX_HOME": home}
    assert [a.id for a in session_pin.launchable_accounts(config, "codex")] == ["codex"]


def test_follow_active_with_one_logged_in_account_picks_it(world):
    root, config = world
    home = add_local(config, root, "codex")
    assert codex_follow.follow_active_account(config) == "codex"
    assert launch_env.account_env(config, family="codex") == {"CODEX_HOME": home}
    assert asyncio.run(create_account._codex_follow_plan()).account_id == "codex"


def test_follow_active_with_several_logged_in_accounts_refuses_and_names_them(world):
    root, config = world
    add_local(config, root, "one")
    add_local(config, root, "two")
    with pytest.raises(codex_follow.CodexAccountRefused) as caught:
        codex_follow.follow_active_account(config)
    assert caught.value.code == "codex_account_choice"
    assert {a["id"] for a in caught.value.accounts} == {"one", "two"}
    assert launch_env.account_env(config, family="codex") == {}


def test_a_logged_out_account_is_not_a_candidate(world):
    root, config = world
    add_local(config, root, "one")
    add_local(config, root, "out", logged_in=False)
    assert codex_follow.follow_active_account(config) == "one"


def test_no_account_and_a_logged_out_default_home_refuses_no_codex_account(world):
    _root, config = world
    with pytest.raises(codex_follow.CodexAccountRefused) as caught:
        codex_follow.follow_active_account(config)
    assert caught.value.code == "no_codex_account"
    with pytest.raises(create_account.CreateAccountRefused) as refused:
        asyncio.run(create_account._codex_follow_plan())
    assert refused.value.code == "no_codex_account"


def test_a_logged_in_default_home_is_kept_when_no_account_is_usable(world):
    root, config = world
    (root / ".codex" / "auth.json").write_text(json.dumps(LOGIN))
    assert codex_follow.follow_active_account(config) is None
    assert asyncio.run(create_account._codex_follow_plan()) == restart_account.NO_PLAN


def test_a_restart_naming_no_account_keeps_the_followed_home_and_refuses_when_none(world, monkeypatch):
    root, config = world
    monkeypatch.setattr(launch_env, "_config_path", lambda: config)
    from src.core.account_switch.pane_account import UNREADABLE

    async def unreadable(_socket, _name, _variable):
        return UNREADABLE

    detail = asyncio.run(launch_env.restart_refusal("s", "n", config_path=config, family="codex", read_profile=unreadable))
    assert detail == launch_env.CODEX_FOLLOW_DETAIL["no_codex_account"]
    home = add_local(config, root, "codex")
    assert asyncio.run(launch_env.restart_refusal("s", "n", config_path=config, family="codex", read_profile=unreadable)) is None
    env = asyncio.run(launch_env.respawn_pane_env({"A": "1"}, family="codex"))
    assert env["CODEX_HOME"] == home and env["CODEX_REFRESH_TOKEN_URL_OVERRIDE"] is None


def test_a_relayed_account_still_gets_the_relay_env(world):
    root, config = world
    relay_home = root / ".carnivore" / "accounts" / RELAY
    relay_home.mkdir()
    (relay_home / "auth.json").write_text(json.dumps(LOGIN))
    assert launch_env.account_env(config, claude_account=RELAY, family="codex") == codex_target.codex_relay_env(str(relay_home))
    assert codex_follow.follow_active_account(config) == RELAY


def _pane(value):
    from src.core.account_switch.pane_account import PaneProfile

    async def read(_socket, _name, _variable):
        return PaneProfile(readable=True, value=value)

    return read


def test_a_restart_keeps_a_pane_on_its_logged_in_default_home(world, monkeypatch):
    root, config = world
    monkeypatch.setattr(launch_env, "_config_path", lambda: config)
    (root / ".codex" / "auth.json").write_text(json.dumps(LOGIN))
    add_local(config, root, "one")
    env = asyncio.run(launch_env.respawn_pane_env({"A": "1"}, family="codex", pane=("s", "n"), read_profile=_pane(None)))
    assert env["CODEX_HOME"] is None
    add_local(config, root, "two")
    assert asyncio.run(launch_env.restart_refusal("s", "n", config_path=config, family="codex", read_profile=_pane(None))) is None


def test_a_restart_keeps_a_pane_on_the_local_account_it_runs_on(world, monkeypatch):
    root, config = world
    monkeypatch.setattr(launch_env, "_config_path", lambda: config)
    one = add_local(config, root, "one")
    add_local(config, root, "two")
    assert asyncio.run(launch_env.restart_refusal("s", "n", config_path=config, family="codex", read_profile=_pane(one))) is None
    env = asyncio.run(launch_env.respawn_pane_env({}, family="codex", pane=("s", "n"), read_profile=_pane(one)))
    assert env["CODEX_HOME"] == one


def test_a_restart_on_a_logged_out_home_still_follows(world, monkeypatch):
    root, config = world
    monkeypatch.setattr(launch_env, "_config_path", lambda: config)
    one = add_local(config, root, "one")
    env = asyncio.run(launch_env.respawn_pane_env({}, family="codex", pane=("s", "n"), read_profile=_pane(None)))
    assert env["CODEX_HOME"] == one


def test_a_recreate_keeps_the_recorded_home_while_it_is_logged_in(world):
    root, config = world
    (root / ".codex" / "auth.json").write_text(json.dumps(LOGIN))
    add_local(config, root, "one")
    add_local(config, root, "two")
    assert codex_follow.recorded_home(config, None) == codex_follow.KeptHome(None)
    assert codex_follow.recorded_home(config, json.dumps({"account": {"id": "two"}})) == codex_follow.KeptHome("two")
    (root / ".codex" / "auth.json").unlink()
    assert codex_follow.recorded_home(config, json.dumps({"account": {"id": None}})) is None


def test_every_codex_credential_shape_counts_as_logged_in(tmp_path):
    for document in ({"personal_access_token": "placeholder"}, {"bedrock_api_key": {"k": "placeholder"}},
                     {"OPENAI_API_KEY": "placeholder"}, LOGIN):
        (tmp_path / "auth.json").write_text(json.dumps(document))
        assert codex_follow.home_logged_in(str(tmp_path)), document
    (tmp_path / "auth.json").write_text(json.dumps({"tokens": {}, "OPENAI_API_KEY": None}))
    assert not codex_follow.home_logged_in(str(tmp_path))


def test_a_gone_pane_finds_its_local_account_home_from_the_record(world, monkeypatch):
    root, config = world
    monkeypatch.setattr(launch_env, "_config_path", lambda: config)
    home = add_local(config, root, "one")
    assert cph._local_account_home("one") == home
    assert cph._local_account_home("missing") is None

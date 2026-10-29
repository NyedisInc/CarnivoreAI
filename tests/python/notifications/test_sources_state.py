
from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.config.provider_accounts import ProviderAccount
from src.core.notifications import contracts
from src.core.notifications.sources import agent_update as agent_update_source
from src.core.notifications.sources import frames, login, restore, update
from src.core.provider_ledger import poller as poller_module
from tests.test_provider_ledger_poller import (
    NOW, FakeClock, FakeFetcher, claude_account, live_claude_credential, ok_outcome)




def _acct(account_id: str, state: str, provider: str = "claude", poke: Any = None) -> Any:
    return SimpleNamespace(id=account_id, name=account_id, provider=provider, credential_state=state, poke=poke)


def test_login_does_not_fire_at_boot_even_when_an_account_is_already_signed_out(captured) -> None:
    watch = login.LoginWatch()
    assert watch.observe([_acct("a", "expired"), _acct("b", "ok")]) == []
    assert captured == []


def test_login_fires_once_on_the_transition_and_not_while_it_stays(captured) -> None:
    watch = login.LoginWatch()
    watch.observe([_acct("a", "ok")])
    assert watch.observe([_acct("a", "expired")]) == ["a"]
    assert watch.observe([_acct("a", "expired")]) == []
    assert watch.observe([_acct("a", "missing")]) == []
    assert [e.type_id for e in captured] == ["provider.needs_login"] and captured[0].session_ref == "a"
    watch.observe([_acct("a", "ok")])
    assert watch.observe([_acct("a", "refused")]) == ["a"]
    assert len(captured) == 2


def test_login_ignores_an_unpolled_account_a_new_account_and_other_providers(captured) -> None:
    watch = login.LoginWatch()
    watch.observe([_acct("a", "unknown")])
    assert watch.observe([_acct("a", "expired"), _acct("n", "expired")]) == []
    watch.observe([_acct("c", "ok", provider="codex")])
    assert watch.observe([_acct("c", "expired", provider="codex")]) == []
    assert captured == []


def test_login_counts_a_needs_login_poke_as_the_state(captured) -> None:
    watch = login.LoginWatch()
    watch.observe([_acct("a", "ok")])
    poke = SimpleNamespace(state="needs_login")
    assert watch.observe([_acct("a", "ok", poke=poke)]) == ["a"]


@pytest.mark.asyncio
async def test_the_poller_publish_feeds_the_login_watch(captured, no_builtin_default_login) -> None:
    creds = {"c": live_claude_credential()}
    clock = FakeClock()
    poller = poller_module.LedgerPoller(
        config_path=lambda: Path("/nonexistent/config.json"), list_accounts=lambda p: [claude_account()],
        clock=clock, random_unit=lambda: 0.5, claude_fetch=FakeFetcher([ok_outcome()]),
        codex_fetch=FakeFetcher([ok_outcome()]), read_claude_credential=lambda d: creds["c"],
        read_claude_identity=lambda d: None, read_codex_credential=lambda h: None, client_factory=lambda: None,
        after_pass=lambda snapshot, state: asyncio.sleep(0))
    await poller.run_pass()
    assert captured == []
    creds["c"] = live_claude_credential().__class__(
        access_token="x", expires_at=NOW - timedelta(minutes=1), refresh_token_expires_at=NOW + timedelta(days=30),
        scopes=("user:profile",), subscription_type="max", rate_limit_tier=None, source="keychain")
    clock.advance(3600)
    await poller.run_pass()
    assert [e.type_id for e in captured if e.session_ref == "Max main"] == ["provider.needs_login"]




def test_update_fires_once_per_version_and_again_for_the_next(captured, tmp_path: Path) -> None:
    assert update.on_available("1.12.0", tmp_path) is True
    assert update.on_available("1.12.0", tmp_path) is False
    assert update.on_available("1.13.0", tmp_path) is True
    assert [e.instance_key for e in captured] == ["update:1.12.0", "update:1.13.0"]
    assert all(e.type_id == "app.update_available" for e in captured)


def test_update_is_remembered_across_a_simulated_restart(captured, tmp_path: Path) -> None:
    update.on_available("1.12.0", tmp_path)
    contracts.uninstall_sink()
    fresh: List[Any] = []
    contracts.install_sink(fresh.append)
    assert update.on_available("1.12.0", tmp_path) is False and fresh == []


def test_update_spends_nothing_when_no_sink_is_installed(tmp_path: Path) -> None:
    contracts.uninstall_sink()
    assert update.on_available("1.12.0", tmp_path) is False
    seen: List[Any] = []
    contracts.install_sink(seen.append)
    try:
        assert update.on_available("1.12.0", tmp_path) is True
    finally:
        contracts.uninstall_sink()


def test_update_checker_store_calls_the_source_only_for_an_available_answer(monkeypatch, tmp_path: Path) -> None:
    from src.core import update_check
    from src.core.update_check import UpdateChecker, UpdateStatus

    calls: List[str] = []
    monkeypatch.setattr(update_check.update_source, "on_available", lambda version, state_dir=None: calls.append(version))
    checker = UpdateChecker(config_path=tmp_path / "c.json", root=tmp_path, cache_path=tmp_path / "cache.json")
    for status, latest in (("current", "1.0.0"), ("unknown", ""), ("update_available", "1.2.0")):
        checker._store(UpdateStatus(status, "1.0.0", latest, "r", 0.0, "", "cmd"))
    assert calls == ["1.2.0"]




def test_restore_fires_once_per_boot(captured) -> None:
    restore.reset_for_tests()
    assert restore.on_offered("o1") is True
    assert restore.on_offered("o2") is False
    assert [e.type_id for e in captured] == ["app.restore_offer"]
    restore.reset_for_tests()
    assert restore.on_offered("o3") is True


def test_restore_does_not_spend_the_boot_when_nobody_is_listening() -> None:
    restore.reset_for_tests()
    contracts.uninstall_sink()
    assert restore.on_offered("o1") is False
    seen: List[Any] = []
    contracts.install_sink(seen.append)
    try:
        assert restore.on_offered("o1") is True
    finally:
        contracts.uninstall_sink()
        restore.reset_for_tests()


def test_the_journal_task_calls_the_restore_source_from_both_offer_paths() -> None:
    import inspect

    from src.core import session_journal_task as task

    for fn in (task._set_offer, task._log_offer):
        assert "restore_source.on_offered" in inspect.getsource(fn)




def _watcher(*pids: int, family: Any = None, known: bool = True) -> Any:
    def observation(pid: int) -> Any:
        registry = SimpleNamespace(known=known, pid=pid)
        return SimpleNamespace(stale=False, evidence=SimpleNamespace(agent_family=family, registry=registry))

    table = {f"ses_{p}": observation(p) for p in pids}
    return SimpleNamespace(observed_session_ids=lambda: list(table), observation_for=lambda sid: table.get(sid))


def _versions(monkeypatch, running: str, installed: str) -> None:
    from src.core.sessions import agent_update as core

    monkeypatch.setattr(agent_update_source, "agent_update_status", lambda *, pid, registry_version=None: core.agent_update_status(
        pid=pid, registry_version=registry_version, running_reader=lambda p: running, installed_reader=lambda: installed))


def test_agent_update_fires_once_per_installed_version_across_a_restart(monkeypatch, captured, tmp_path: Path) -> None:
    _versions(monkeypatch, "2.1.283", "2.1.284")
    assert agent_update_source.check_once(_watcher(1), tmp_path) is True
    assert agent_update_source.check_once(_watcher(1), tmp_path) is False
    contracts.uninstall_sink()
    contracts.install_sink(captured.append)
    assert agent_update_source.check_once(_watcher(1), tmp_path) is False
    _versions(monkeypatch, "2.1.283", "2.1.285")
    assert agent_update_source.check_once(_watcher(1), tmp_path) is True
    assert [e.instance_key for e in captured] == ["agent_update:2.1.284", "agent_update:2.1.285"]
    assert captured[0].type_id == "agent.update_ready"


def test_agent_update_is_quiet_when_nothing_is_older_or_unmeasurable(monkeypatch, captured, tmp_path: Path) -> None:
    _versions(monkeypatch, "2.1.284", "2.1.284")
    assert agent_update_source.check_once(_watcher(1), tmp_path) is False
    _versions(monkeypatch, "2.1.283", "2.1.284")
    assert agent_update_source.check_once(_watcher(1, family="codex"), tmp_path) is False
    assert agent_update_source.check_once(_watcher(1, known=False), tmp_path) is False
    assert agent_update_source.check_once(None, tmp_path) is False
    assert captured == []


def test_the_agent_update_loop_survives_a_failed_pass(monkeypatch) -> None:
    calls: List[int] = []

    def flaky(watcher: Any, state_dir: Any = None) -> bool:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("boom")
        return False

    monkeypatch.setattr(agent_update_source, "check_once", flaky)

    async def scenario() -> None:
        task = asyncio.create_task(agent_update_source.run(lambda: None, interval=0.01))
        await asyncio.sleep(0.1)
        task.cancel()

    asyncio.run(scenario())
    assert len(calls) >= 2




def test_auto_slept_emits_with_the_session_facts(captured) -> None:
    info = SimpleNamespace(tmux_session="cloude_api", project_name="api")
    frames.auto_slept("ses_1", "uuid-1", "API", info)
    event = captured[0]
    assert (event.type_id, event.session_id, event.tmux_name, event.project) == ("session.auto_slept", "ses_1", "cloude_api", "api")
    assert event.session_uuid == "uuid-1"


def test_account_switched_emits_for_a_recorded_switch(captured) -> None:
    frames.account_switched({"to_account_id": "max-2", "at": "2026-10-03T00:00:00+00:00"})
    assert captured[0].type_id == "account.switched" and "max-2" in captured[0].instance_key


def test_the_real_raise_points_emit(captured) -> None:
    import inspect

    from src.core.account_switch import auto_switch
    from src.core.auto_sleep import sleeper

    assert "frames.account_switched(entry)" in inspect.getsource(auto_switch.record_switch)
    assert "frames.auto_slept(" in inspect.getsource(sleeper.AutoSleeper._act)

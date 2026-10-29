
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from src.config.provider_account_switch import ProviderAccountSwitchConfig
from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR, ProviderAccount
from src.core.account_switch import auto_switch
from src.core.account_switch.active import effective_active, pointer_for
from src.core.provider_ledger import default_login, poller_scan
from src.models.provider_ledger import (
    AccountUsage,
    LedgerSnapshot,
    LedgerTotal,
    LoopStatus,
    UsageWindow,
)

AUTO = poller_scan.AUTO_DEFAULT_ACCOUNT_ID
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
MINE = {"accountUuid": "acct-mine", "organizationUuid": "org-mine"}
OTHER = {"accountUuid": "acct-other", "organizationUuid": "org-other"}


@pytest.fixture()
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(default_login, "_IDENTITY_CACHE", {}, raising=False)
    return tmp_path


def _identity(path: Path, oauth: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"oauthAccount": oauth}))


def _managed(home: Path, account_id: str, oauth: dict) -> ProviderAccount:
    directory = home / ".carnivore" / "accounts" / account_id
    _identity(directory / ".claude.json", oauth)
    return ProviderAccount(
        id=account_id, name=account_id, provider="claude",
        claude_config_dir=str(directory), managed=True,
    )


def _ids(rows: List[ProviderAccount]) -> List[str]:
    return [row.id for row in rows]


def test_an_empty_list_gets_the_default_row(home):
    result = poller_scan.with_auto_default([])
    assert _ids(result) == [AUTO]
    row = result[0]
    assert (row.provider, row.claude_config_dir, row.managed) == (
        "claude", DEFAULT_CLAUDE_CONFIG_DIR, False,
    )


def test_a_managed_row_gets_the_default_row_beside_it(home):
    _identity(home / ".claude.json", MINE)
    member = _managed(home, "sam-initech", OTHER)
    assert _ids(poller_scan.with_auto_default([member])) == ["sam-initech", AUTO]


def test_a_codex_row_never_stands_for_the_claude_default(home):
    codex = ProviderAccount(id="cx", name="cx", provider="codex", codex_home="~/.codex")
    assert _ids(poller_scan.with_auto_default([codex])) == ["cx", AUTO]


@pytest.mark.parametrize("spelling", ["tilde", "absolute"])
def test_a_configured_row_at_the_default_dir_is_not_duplicated(home, spelling):
    pointer = DEFAULT_CLAUDE_CONFIG_DIR if spelling == "tilde" else str(home / ".claude")
    mine = ProviderAccount(id="mine", name="Mine", provider="claude", claude_config_dir=pointer)
    assert poller_scan.with_auto_default([mine]) == [mine]


def test_a_profile_signed_in_as_the_default_identity_is_not_duplicated(home):
    _identity(home / ".claude.json", MINE)
    same = _managed(home, "sam-main", MINE)
    assert poller_scan.with_auto_default([same]) == [same]


def test_a_default_login_with_no_readable_identity_is_still_listed(home):
    other = _managed(home, "sam-initech", OTHER)
    assert _ids(poller_scan.with_auto_default([other])) == ["sam-initech", AUTO]


def test_it_is_never_written_to_the_configured_list(home):
    configured: List[ProviderAccount] = []
    poller_scan.with_auto_default(configured)
    assert configured == []




def test_the_default_row_is_the_active_account_when_no_pointer_is_set(home):
    member = _managed(home, "sam-initech", OTHER)
    accounts = poller_scan.with_auto_default([member])
    active = effective_active(accounts, ProviderAccountSwitchConfig(), "claude")
    assert (active.account_id, active.source) == (AUTO, "default_login")


def test_activating_the_default_row_means_no_pointer(home):
    assert pointer_for(poller_scan.default_login_row()) is None
    member = _managed(home, "sam-initech", OTHER)
    assert pointer_for(member) == "sam-initech"


def _usage(account_id: str, short: float, state: str = "ok") -> AccountUsage:
    return AccountUsage(
        id=account_id, name=account_id, provider="claude", credential_state=state,
        windows=[UsageWindow(
            kind="five_hour", label="5h", used_pct=short,
            window_seconds=18000, resets_at=NOW + timedelta(hours=2),
        )],
    )


def _snapshot(rows: List[AccountUsage]) -> LedgerSnapshot:
    return LedgerSnapshot(
        accounts=rows, total=LedgerTotal(accounts=len(rows)), loop=LoopStatus(alive=True)
    )


def test_auto_switch_can_move_onto_the_default_login(home):
    member = _managed(home, "sam-initech", OTHER)
    accounts = poller_scan.with_auto_default([member])
    switch = ProviderAccountSwitchConfig(auto_switch=True, active_claude="sam-initech")
    snap = _snapshot([_usage("sam-initech", 99.5), _usage(AUTO, 5)])
    moved = auto_switch.plan_switches(snap, accounts, switch, now=NOW)
    assert [(d.from_account_id, d.to_account_id) for d in moved] == [("sam-initech", AUTO)]
    assert auto_switch._pointer_of_decision(accounts, moved[0]) is None


def test_auto_switch_can_move_off_the_default_login(home):
    member = _managed(home, "sam-initech", OTHER)
    accounts = poller_scan.with_auto_default([member])
    switch = ProviderAccountSwitchConfig(auto_switch=True)
    snap = _snapshot([_usage("sam-initech", 5), _usage(AUTO, 99.5)])
    moved = auto_switch.plan_switches(
        snap, accounts, switch, now=NOW, linkable=lambda _a: True
    )
    assert [(d.from_account_id, d.to_account_id) for d in moved] == [(AUTO, "sam-initech")]


@pytest.mark.parametrize("state", ["expired", "missing", "refused", "unknown"])
def test_the_default_login_is_not_a_candidate_unless_its_credential_is_ok(home, state):
    member = _managed(home, "sam-initech", OTHER)
    accounts = poller_scan.with_auto_default([member])
    switch = ProviderAccountSwitchConfig(auto_switch=True, active_claude="sam-initech")
    snap = _snapshot([_usage("sam-initech", 99.5), _usage(AUTO, 5, state=state)])
    assert auto_switch.plan_switches(snap, accounts, switch, now=NOW) == []


def test_the_default_login_needs_no_links_and_no_setup(home):
    assert auto_switch._linkable(poller_scan.default_login_row()) is True

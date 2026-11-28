
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config.provider_account_switch import ProviderAccountSwitchConfig, pointer_field
from src.config.provider_accounts import ProviderAccount, has_profile_dir, profile_dir_for
from src.core.agy import ledger
from src.core.provider_ledger.poller_core import LedgerPoller
from src.models.provider_ledger import AccountUsage

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def write_state(folder: Path, pid: int, **fields) -> None:
    (folder / "agy-state").mkdir(parents=True, exist_ok=True)
    (folder / "agy-state" / ("%d.json" % pid)).write_text(json.dumps(fields))


def test_windows_from_state_maps_used_disabled_and_reset():
    state = {"written_at": NOW.timestamp(), "quota": {
        "gemini-5h": {"remaining_fraction": 0.25, "reset_time": (NOW + timedelta(hours=2)).isoformat()},
        "gemini-weekly": {"remaining_fraction": 0.9, "reset_in_seconds": 3600},
        "3p-5h": {"disabled": True},
        "junk": "x",
    }}
    rows = {w.kind: w for w in ledger.windows_from_state(state, NOW)}
    assert rows["gemini-5h"].used_pct == 75.0 and rows["gemini-5h"].label == "5h" and rows["gemini-5h"].window_seconds == 18000
    assert rows["gemini-5h"].resets_at == NOW + timedelta(hours=2)
    assert rows["gemini-weekly"].label == "7d" and rows["gemini-weekly"].used_pct == 10.0
    assert rows["gemini-weekly"].resets_at == NOW + timedelta(hours=1)
    assert rows["3p-5h"].used_pct == 100.0 and "junk" not in rows


def test_a_lapsed_window_reads_as_reset():
    state = {"quota": {"gemini-5h": {"remaining_fraction": 0.0, "reset_time": (NOW - timedelta(minutes=1)).isoformat()}}}
    window = ledger.windows_from_state(state, NOW)[0]
    assert window.used_pct == 0.0 and window.resets_at is None


def test_newest_state_matches_the_account_by_its_email_slug(tmp_path):
    write_state(tmp_path, 1, email="a@x.com", written_at=10, plan_tier="pro")
    write_state(tmp_path, 2, email="b@x.com", written_at=20)
    write_state(tmp_path, 3, email="a@x.com", written_at=30, plan_tier="ultra")
    write_state(tmp_path, 4, written_at=99)
    assert ledger.newest_state(tmp_path)["email"] == "a@x.com"
    assert ledger.newest_state(tmp_path, "agy-a-x-com")["plan_tier"] == "ultra"
    assert ledger.newest_state(tmp_path, "agy-nobody") is None
    reading = ledger.reading_for(tmp_path, "agy-b-x-com", True)
    assert reading["credential_state"] == "ok" and reading["identity"] == "b@x.com"
    assert ledger.reading_for(tmp_path, "agy-b-x-com", False)["credential_state"] == "missing"


def test_antigravity_kind_round_trips_with_no_profile_directory():
    account = ProviderAccount(id="agy-a-x-com", name="a@x.com", provider="antigravity")
    assert ProviderAccount(**account.model_dump()) == account
    assert has_profile_dir("antigravity") is False and profile_dir_for(account) == ""
    switch = ProviderAccountSwitchConfig(active_antigravity="agy-a-x-com")
    assert switch.active_for("antigravity") == "agy-a-x-com" and pointer_field("antigravity") == "active_antigravity"
    row = AccountUsage(id=account.id, name=account.name, provider="antigravity", credential_state="ok")
    assert AccountUsage(**row.model_dump()).provider == "antigravity"


def test_poller_reads_an_antigravity_account_without_any_http_call(tmp_path, monkeypatch):
    from src.config import settings
    from src.core.agy import accounts as agy_accounts

    write_state(tmp_path, 7, email="a@x.com", written_at=NOW.timestamp(), plan_tier="pro",
                quota={"gemini-5h": {"remaining_fraction": 0.5, "reset_time": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()}})
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path)
    monkeypatch.setattr(agy_accounts, "has_copy", lambda account_id: True)
    account = ProviderAccount(id="agy-a-x-com", name="a@x.com", provider="antigravity")

    def no_http(*args, **kwargs):
        raise AssertionError("an antigravity account must never hit an HTTP usage call")

    poller = LedgerPoller(list_accounts=lambda path: [account], claude_fetch=no_http, codex_fetch=no_http,
                          client_factory=lambda: None, config_path=lambda: tmp_path / "config.json")
    asyncio.run(poller.run_pass())
    row = poller.snapshot().accounts[0]
    assert row.provider == "antigravity" and row.credential_state == "ok"
    assert row.identity == "a@x.com" and row.plan == "pro"
    assert [(w.kind, w.used_pct) for w in row.windows] == [("gemini-5h", 50.0)]


from __future__ import annotations

import asyncio
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.config import settings
from src.config.provider_accounts import ProviderAccount, managed_dir_for
from src.core import config_writer
from src.core.account_switch import auto_switch, launch_env, profile_setup, store
from src.core.provider_ledger import accounts_store, managed_profiles, refresh_guard
from src.models.provider_ledger import AccountUsage, LedgerSnapshot, LedgerTotal, LoopStatus, UsageWindow
from tests.helpers.claude_profile import refuse_writes_outside, temp_home, write_claude_profile

REAL_HOME = os.path.expanduser("~")


@pytest.fixture(autouse=True)
def second_stop(tmp_path, monkeypatch):
    refused = refuse_writes_outside(tmp_path, monkeypatch)
    yield refused
    assert refused == [], "a real path was reached"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    return temp_home(tmp_path, monkeypatch, default={"hasCompletedOnboarding": True})


@pytest.fixture()
def config(home, monkeypatch):
    path = home / "config.json"
    path.write_text(json.dumps({"agents": {}}))
    for account_id in ("ready", "fresh"):
        managed_profiles.ensure_managed_dir(account_id)
        accounts_store.upsert_account(path, ProviderAccount(
            id=account_id, name=account_id, provider="claude",
            claude_config_dir=managed_dir_for(account_id), managed=True,
        ))
    write_claude_profile(managed_dir_for("ready"))
    write_claude_profile(managed_dir_for("fresh"), setup_complete=False,
                         extra={"userID": "u-1", "projects": {"/w": {"allowedTools": []}}})
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    return path


def accounts(config):
    return accounts_store.list_accounts(config)


def account(config, account_id: str) -> ProviderAccount:
    return next(a for a in accounts(config) if a.id == account_id)


def row(account_id: str, state: str = "ok", pct: float = 5.0) -> AccountUsage:
    return AccountUsage(
        id=account_id, name=account_id, provider="claude", credential_state=state,
        windows=[UsageWindow(kind="five_hour", label="5h", used_pct=pct, window_seconds=18000,
                             resets_at=datetime(2030, 1, 1, tzinfo=timezone.utc))],
    )


def profile_json(account_id: str) -> dict:
    return json.loads((Path(managed_dir_for(account_id)) / ".claude.json").read_text())


def mode_of(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)




def test_a_login_the_ledger_reads_ok_is_marked_setup_done(config):
    assert profile_setup.setup_done(account(config, "fresh")) is False
    outcome = profile_setup.converge([row("fresh")], accounts(config))
    assert outcome == {"fresh": profile_setup.WROTE}
    doc = profile_json("fresh")
    assert doc["hasCompletedOnboarding"] is True
    assert doc["oauthAccount"] == {"emailAddress": "someone@example.invalid"}
    assert doc["userID"] == "u-1" and doc["projects"] == {"/w": {"allowedTools": []}}
    assert profile_setup.setup_done(account(config, "fresh")) is True


@pytest.mark.parametrize("state", ["expired", "missing", "refused", "unknown", "error", "rate_limited"])
def test_only_a_login_the_ledger_reads_ok_is_marked(config, state):
    before = profile_json("fresh")
    assert profile_setup.converge([row("fresh", state)], accounts(config)) == {}
    assert profile_json("fresh") == before


def test_a_profile_whose_login_has_not_written_its_identity_is_not_marked(config):
    path = Path(managed_dir_for("fresh")) / ".claude.json"
    path.write_text(json.dumps({"firstStartTime": "x"}))
    assert profile_setup.converge([row("fresh")], accounts(config)) == {"fresh": profile_setup.NOT_SIGNED_IN}
    assert json.loads(path.read_text()) == {"firstStartTime": "x"}


def test_an_unmanaged_profile_and_the_default_login_are_never_written(config, home):
    unmanaged_dir = home / "hand-made"
    unmanaged_dir.mkdir()
    write_claude_profile(str(unmanaged_dir), setup_complete=False)
    rows = [
        ProviderAccount(id="mine", name="mine", provider="claude", claude_config_dir=str(unmanaged_dir)),
        ProviderAccount(id="default", name="default", provider="claude", claude_config_dir="~/.claude"),
    ]
    default_before = (home / ".claude.json").read_bytes()
    mine_before = (unmanaged_dir / ".claude.json").read_bytes()
    assert profile_setup.converge([row("mine"), row("default")], rows) == {}
    assert (home / ".claude.json").read_bytes() == default_before
    assert (unmanaged_dir / ".claude.json").read_bytes() == mine_before


def test_a_converged_profile_is_not_written_again(config):
    profile_setup.converge([row("fresh"), row("ready")], accounts(config))
    stamp = os.stat(Path(managed_dir_for("fresh")) / ".claude.json").st_mtime_ns
    assert set(profile_setup.converge([row("fresh"), row("ready")], accounts(config)).values()) == {
        profile_setup.CONVERGED
    }
    assert os.stat(Path(managed_dir_for("fresh")) / ".claude.json").st_mtime_ns == stamp


def test_the_file_and_its_backup_stay_0600_under_a_permissive_umask(config):
    old = os.umask(0o022)
    try:
        profile_setup.converge([row("fresh")], accounts(config))
    finally:
        os.umask(old)
    profile = Path(managed_dir_for("fresh"))
    assert mode_of(profile / ".claude.json") == 0o600
    assert mode_of(profile / ".claude.json.bak") == 0o600


def test_the_hook_converges_through_the_ledger_pass(config):
    snap = LedgerSnapshot(accounts=[row("fresh")], total=LedgerTotal(accounts=1), loop=LoopStatus(alive=True))
    assert asyncio.run(profile_setup.after_pass(snap)) == {"fresh": profile_setup.WROTE}




def test_auto_switch_skips_an_account_whose_setup_is_not_done(config):
    fresh = account(config, "fresh")
    ready = account(config, "ready")
    assert auto_switch._linkable(fresh) is False
    assert auto_switch._linkable(ready) is True
    profile_setup.converge([row("fresh")], accounts(config))
    assert auto_switch._linkable(fresh) is True


def test_a_new_or_restarted_pane_is_never_launched_onto_an_unmarked_profile(config):
    store.set_active(config, "claude", "fresh")
    assert launch_env.account_env(config) == {}
    store.set_active(config, "claude", "ready")
    assert launch_env.account_env(config) == {"CLAUDE_CONFIG_DIR": managed_dir_for("ready")}


def test_the_ledger_row_carries_the_setup_state(config):
    from src.core.provider_ledger.credentials import read_claude_identity

    assert read_claude_identity(managed_dir_for("fresh")).setup_complete is False
    assert read_claude_identity(managed_dir_for("ready")).setup_complete is True
    assert AccountUsage(id="x", name="x", provider="claude", credential_state="ok").setup_complete is None


def test_activating_an_unmarked_account_is_refused_with_a_reason(config):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router as api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        response = client.post("/api/v1/provider-ledger/accounts/fresh/activate")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "profile_needs_setup"
        assert store.read_switch(config).active_claude is None
        assert client.post("/api/v1/provider-ledger/accounts/ready/activate").status_code == 200




def test_a_simulated_external_rewrite_is_converged_again(config):
    profile_setup.converge([row("fresh")], accounts(config))
    path = Path(managed_dir_for("fresh")) / ".claude.json"
    stale = {k: v for k, v in json.loads(path.read_text()).items() if k != "hasCompletedOnboarding"}
    stale["numStartups"] = 3
    path.write_text(json.dumps(stale))
    assert profile_setup.converge([row("fresh")], accounts(config)) == {"fresh": profile_setup.WROTE}
    doc = json.loads(path.read_text())
    assert doc["hasCompletedOnboarding"] is True
    assert doc["numStartups"] == 3


def test_a_write_that_lands_between_our_read_and_replace_wins(config, monkeypatch):
    path = Path(managed_dir_for("fresh")) / ".claude.json"
    real = config_writer._replace_atomically

    def claude_writes_first(target, data, **kwargs):
        target.write_text(json.dumps({"oauthAccount": {"emailAddress": "x"}, "numStartups": 9}))
        return real(target, data, **kwargs)

    monkeypatch.setattr(config_writer, "_replace_atomically", claude_writes_first)
    assert profile_setup.converge([row("fresh")], accounts(config)) == {"fresh": profile_setup.RACED}
    assert json.loads(path.read_text())["numStartups"] == 9
    assert list(path.parent.glob("*.tmp")) == []


def test_a_refresh_in_progress_defers_the_write(config, monkeypatch):
    monkeypatch.setattr(refresh_guard, "busy_reason", lambda profile: refresh_guard.BUSY_REFRESH_LOCK)
    before = profile_json("fresh")
    assert profile_setup.converge([row("fresh")], accounts(config)) == {"fresh": profile_setup.DEFERRED}
    assert profile_json("fresh") == before


def test_a_live_claude_waits_for_a_still_file_then_writes(config, monkeypatch):
    monkeypatch.setattr(refresh_guard, "busy_reason", lambda profile: refresh_guard.BUSY_CLAUDE_RUNNING)
    assert profile_setup.converge([row("fresh")], accounts(config)) == {"fresh": profile_setup.DEFERRED}
    path = Path(managed_dir_for("fresh")) / ".claude.json"
    old = path.stat().st_mtime - profile_setup.FILE_QUIET_SECONDS - 1
    os.utime(path, (old, old))
    assert profile_setup.converge([row("fresh")], accounts(config)) == {"fresh": profile_setup.WROTE}




def test_the_second_stop_refuses_the_real_default_login_file(second_stop, home):
    real = Path(REAL_HOME) / ".claude.json"
    assert not str(real).startswith(str(home))
    before = real.stat().st_mtime_ns if real.exists() else None
    with pytest.raises(AssertionError):
        config_writer._replace_atomically(real, {"never": "written"})
    assert len(second_stop) == 1 and Path(second_stop[0]).parent == real.parent
    assert Path(second_stop[0]).name.startswith(".claude.json.") and not Path(second_stop[0]).exists()
    assert (real.stat().st_mtime_ns if real.exists() else None) == before
    second_stop.clear()

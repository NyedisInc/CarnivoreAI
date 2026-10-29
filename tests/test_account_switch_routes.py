
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.routes import router as api_router
from src.config import settings
from src.config.provider_accounts import ProviderAccount, managed_dir_for
from src.core.provider_ledger import accounts_store, managed_profiles
from tests.helpers.claude_profile import write_claude_profile

SWITCH_URL = "/api/v1/provider-ledger/switch"


@pytest.fixture()
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude" / "projects").mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {}}))
    for account_id, provider in (("work", "claude"), ("play", "claude"), ("cx", "codex")):
        managed_profiles.ensure_managed_dir(account_id)
        if provider == "claude":
            write_claude_profile(managed_dir_for(account_id))
        pointer = {"claude_config_dir" if provider == "claude" else "codex_home": managed_dir_for(account_id)}
        accounts_store.upsert_account(path, ProviderAccount(
            id=account_id, name=account_id, provider=provider, managed=True, **pointer,
        ))
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    settings._auth_config_cache = None
    return path


@pytest.fixture()
def client(config):
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as test_client:
        yield test_client


def test_the_default_state_is_off_at_ninety_nine_with_nothing_chosen(client):
    body = client.get(SWITCH_URL).json()
    assert body["auto_switch"] is False
    assert body["threshold_percent"] == 99
    assert [(a["provider"], a["account_id"], a["source"]) for a in body["active"]] == [
        ("claude", "auto-claude-default", "default_login"),
    ]
    assert body["restarts_running_sessions"] is False


def test_the_toggle_turns_on_and_off_and_persists(client, config):
    assert client.put(SWITCH_URL, json={"auto_switch": True}).json()["auto_switch"] is True
    assert json.loads(config.read_text())["provider_account_switch"]["auto_switch"] is True
    assert client.put(SWITCH_URL, json={"auto_switch": False}).json()["auto_switch"] is False


def test_a_threshold_outside_the_bounds_is_refused(client):
    assert client.put(SWITCH_URL, json={"auto_switch": True, "threshold_percent": 20}).status_code == 422


def test_a_token_in_the_body_is_refused(client):
    response = client.put(SWITCH_URL, json={"auto_switch": True, "token": "x"})
    assert response.status_code == 422


def test_activating_an_account_points_new_sessions_at_it(client, config):
    response = client.post("/api/v1/provider-ledger/accounts/work/activate")
    assert response.status_code == 200
    body = response.json()
    claude = next(a for a in body["state"]["active"] if a["provider"] == "claude")
    assert (claude["account_id"], claude["source"]) == ("work", "pointer")
    assert body["running_elsewhere"] == []
    assert json.loads(config.read_text())["provider_account_switch"]["active_claude"] == "work"
    assert (Path(managed_dir_for("work")) / "projects").is_symlink()
    assert body["state"]["last_switch"]["reason"] == "manual"


def test_a_codex_account_is_refused_and_the_claude_pointer_is_untouched(client, config):
    client.post("/api/v1/provider-ledger/accounts/work/activate")
    response = client.post("/api/v1/provider-ledger/accounts/cx/activate")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "provider_not_switchable"
    stored = json.loads(config.read_text())["provider_account_switch"]
    assert (stored["active_claude"], stored["active_codex"]) == ("work", None)


def test_a_hand_written_profile_is_refused(client, config, tmp_path):
    mine = tmp_path / ".claude-work"
    mine.mkdir()
    accounts_store.upsert_account(config, ProviderAccount(
        id="mine", name="mine", provider="claude", claude_config_dir=str(mine),
    ))
    response = client.post("/api/v1/provider-ledger/accounts/mine/activate")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "profile_not_managed"


def test_a_corrupt_config_is_a_500_not_a_threshold_complaint(client, config):
    config.write_text("{not json")
    response = client.put(SWITCH_URL, json={"auto_switch": True})
    assert response.status_code == 500


def test_an_unknown_account_is_a_404(client):
    assert client.post("/api/v1/provider-ledger/accounts/nobody/activate").status_code == 404


def test_a_profile_that_keeps_its_own_history_is_refused_and_nothing_moves(client, config):
    (Path(managed_dir_for("play")) / "projects").mkdir()
    response = client.post("/api/v1/provider-ledger/accounts/play/activate")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "profile_not_shared"
    assert "provider_account_switch" not in json.loads(config.read_text())


def test_the_running_list_answers_empty_without_a_session_manager(client):
    assert client.get(SWITCH_URL + "/running").json() == []


SETUP_URL = "/api/v1/provider-ledger/accounts/{}/setup"


def _ledger_reads(monkeypatch, **states):
    from types import SimpleNamespace

    from src.core.provider_ledger import poller

    rows = [SimpleNamespace(id=i, provider="claude", credential_state=s) for i, s in states.items()]
    monkeypatch.setattr(poller, "snapshot", lambda: SimpleNamespace(accounts=rows))


def test_setup_on_an_ok_login_marks_it_done_and_never_switches(client, config, monkeypatch):
    path = write_claude_profile(managed_dir_for("play"), setup_complete=False)
    _ledger_reads(monkeypatch, play="ok")
    response = client.post(SETUP_URL.format("play"))
    assert response.status_code == 200
    assert response.json() == {"outcome": "done"}
    assert json.loads(path.read_text())["hasCompletedOnboarding"] is True
    assert "provider_account_switch" not in json.loads(config.read_text())


def test_setup_on_a_login_that_is_not_ok_asks_for_the_login_and_writes_nothing(client, monkeypatch):
    path = write_claude_profile(managed_dir_for("play"), setup_complete=False)
    _ledger_reads(monkeypatch, play="expired")
    assert client.post(SETUP_URL.format("play")).json() == {"outcome": "login"}
    assert "hasCompletedOnboarding" not in json.loads(path.read_text())


def test_setup_refuses_a_hand_written_profile_and_an_unknown_id(client, config, tmp_path):
    mine = tmp_path / ".claude-mine"
    mine.mkdir()
    accounts_store.upsert_account(config, ProviderAccount(
        id="mine", name="mine", provider="claude", claude_config_dir=str(mine),
    ))
    response = client.post(SETUP_URL.format("mine"))
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "profile_not_managed")
    assert client.post(SETUP_URL.format("nobody")).status_code == 404


def test_activating_the_built_in_login_clears_the_pointer(client, config):
    client.post("/api/v1/provider-ledger/accounts/work/activate")
    response = client.post("/api/v1/provider-ledger/accounts/auto-claude-default/activate")
    assert response.status_code == 200
    claude = next(a for a in response.json()["state"]["active"] if a["provider"] == "claude")
    assert (claude["account_id"], claude["source"]) == ("auto-claude-default", "default_login")
    written = json.loads(config.read_text())
    assert written["provider_account_switch"]["active_claude"] is None
    assert "auto-claude-default" not in json.dumps(written.get("provider_accounts", {}))


def test_the_accounts_list_stays_the_configured_list(client):
    ids = [a["id"] for a in client.get("/api/v1/provider-ledger/accounts").json()]
    assert sorted(ids) == ["cx", "play", "work"]


def test_next_order_leaves_out_an_account_auto_switch_cannot_link(client, config, monkeypatch):
    from types import SimpleNamespace

    from src.core.account_switch import auto_switch
    from src.core.provider_ledger import poller
    from datetime import datetime, timedelta, timezone

    from src.models.provider_ledger import AccountUsage, UsageWindow

    def row(account_id):
        week = UsageWindow(
            kind="seven_day", label="7d", used_pct=10.0, window_seconds=604800,
            resets_at=datetime.now(timezone.utc) + timedelta(days=3),
        )
        return AccountUsage(
            id=account_id, name=account_id, provider="claude",
            credential_state="ok", windows=[week],
        )


    monkeypatch.setattr(poller, "snapshot", lambda: SimpleNamespace(accounts=[row("work"), row("play")]))
    monkeypatch.setattr(auto_switch, "_linkable", lambda account: True)
    assert client.post("/api/v1/provider-ledger/accounts/work/activate").status_code == 200
    first = client.get(SWITCH_URL).json()["active"]
    assert [a["next_order"] for a in first if a["provider"] == "claude"] == [["play"]]
    monkeypatch.setattr(auto_switch, "_linkable", lambda account: account.id != "play")
    second = client.get(SWITCH_URL).json()["active"]
    assert [a["next_order"] for a in second if a["provider"] == "claude"] == [[]]


from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import provider_agy_routes as routes
from src.api.auth import require_auth
from src.core.account_switch import agy_rotate


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(routes, "_config_path", lambda: "config.json")
    monkeypatch.setattr(routes.poller, "poll_soon", lambda account_id: None)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(username="alice")
    app.include_router(routes.router, prefix="/api/v1")
    return TestClient(app)


def test_the_capture_route_answers_the_account_it_made(monkeypatch) -> None:
    monkeypatch.setattr(agy_rotate, "capture_account", lambda path: (SimpleNamespace(id="agy-alice-example-com", name="alice@example.com"), True))
    response = _client(monkeypatch).post("/api/v1/provider-ledger/agy/capture")
    assert response.status_code == 200
    assert response.json() == {"account_id": "agy-alice-example-com", "name": "alice@example.com", "created": True}


def test_the_capture_route_names_why_it_refused(monkeypatch) -> None:
    def refuse(path):
        raise agy_rotate.CaptureError("no_live_login")

    monkeypatch.setattr(agy_rotate, "capture_account", refuse)
    response = _client(monkeypatch).post("/api/v1/provider-ledger/agy/capture")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "agy_no_live_login"


def test_capture_account_defaults_name_to_handle_without_domain(tmp_path, monkeypatch) -> None:
    from src.core.agy import accounts as agy_accounts, ledger as agy_ledger
    from src.core.account_switch import store as switch_store
    from src.core.provider_ledger import accounts_store

    monkeypatch.setattr(agy_ledger, "newest_state", lambda _sd: {"email": "bob@example.com"})
    monkeypatch.setattr(agy_accounts, "snapshot", lambda _aid: None)
    saved = []
    monkeypatch.setattr(accounts_store, "list_accounts", lambda _p: [])
    monkeypatch.setattr(accounts_store, "upsert_account", lambda _p, acct: saved.append(acct))
    monkeypatch.setattr(switch_store, "set_active", lambda _p, _prov, _aid: None)

    acct, created = agy_rotate.capture_account(tmp_path / "config.json", state_dir=tmp_path)
    assert created is True
    assert acct.id == "agy-bob-example-com"
    assert acct.name == "bob"
    assert saved and saved[0].name == "bob"

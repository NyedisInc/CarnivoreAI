
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.core.api_keys import store as store_module


@pytest.fixture
def owner_jwt(monkeypatch) -> str:
    from src.api import auth
    from src.config import settings as real_settings

    fake_auth = SimpleNamespace(
        jwt_secret="test-secret-for-api-key-tests", jwt_expiry_minutes=60,
        access_token_ttl_seconds=900, refresh_token_ttl_seconds=604800,
        refresh_grace_seconds=10, totp_secret="X" * 32,
    )

    class _FakeSettings:
        def load_auth_config(self):
            return fake_auth

        def __getattr__(self, name):
            return getattr(real_settings, name)

    monkeypatch.setattr("src.api.auth.settings", _FakeSettings())
    token, _ = auth.create_access_token()
    return token


@pytest.fixture
def key_store(monkeypatch, tmp_path) -> store_module.ApiKeyStore:
    store = store_module.ApiKeyStore(tmp_path / store_module.DB_NAME)
    monkeypatch.setattr(store_module, "get_store", lambda: store)
    monkeypatch.setattr("src.core.api_keys.gate.get_store", lambda: store)
    monkeypatch.setattr("src.api.api_keys_routes.get_store", lambda: store)
    return store


@pytest.fixture
def client() -> TestClient:
    from src.main import app

    return TestClient(app, client=("127.0.0.1", 50000), raise_server_exceptions=False)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}

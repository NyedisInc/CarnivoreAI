
from __future__ import annotations

import pytest

from src.core.api_keys import fence
from tests.python.api_keys.conftest import bearer
from tests.test_route_auth_inventory import _walk

FORBIDDEN = {"reason": fence.REASON}


@pytest.fixture
def live_key(key_store) -> tuple[dict, str]:
    return key_store.create("script")


def test_key_management_refuses_a_key_and_takes_the_owner(client, owner_jwt, key_store, live_key):
    row, secret = live_key
    for method, path, body in (("POST", "/api/v1/api-keys", {"name": "more"}), ("GET", "/api/v1/api-keys", None),
                               ("DELETE", f"/api/v1/api-keys/{row['id']}", None)):
        r = client.request(method, path, json=body, headers=bearer(secret))
        assert r.status_code == 403 and r.json()["detail"] == FORBIDDEN, (method, path, r.text)
    assert client.get("/api/v1/api-keys", headers=bearer(owner_jwt)).status_code == 200
    assert client.post("/api/v1/api-keys", json={"name": "more"}, headers=bearer(owner_jwt)).status_code == 201
    assert client.delete(f"/api/v1/api-keys/{row['id']}", headers=bearer(owner_jwt)).status_code == 200


def test_auth_routes_refuse_a_key_and_take_the_owner(client, owner_jwt, key_store, live_key):
    _, secret = live_key
    r = client.get("/api/v1/auth/status", headers=bearer(secret))
    assert r.status_code == 403 and r.json()["detail"] == FORBIDDEN, r.text
    assert client.get("/api/v1/auth/status", headers=bearer(owner_jwt)).status_code == 200
    for path, body in (("/api/v1/auth/verify", {"code": "000000"}), ("/api/v1/auth/refresh", {"refresh_token": "x"}),
                       ("/api/v1/auth/logout", {"refresh_token": "x"})):
        r = client.post(path, json=body, headers=bearer(secret))
        assert r.status_code != 200 and "access_token" not in r.text, (path, r.text)


def test_mcp_token_minting_refuses_a_key_and_takes_the_owner(client, owner_jwt, key_store, live_key, monkeypatch, tmp_path):
    from src.core.mcp import token_store

    tokens = token_store.TokenStore(tmp_path)
    monkeypatch.setattr(token_store, "get_store", lambda: tokens)
    _, secret = live_key
    for method, path, body in (("GET", "/api/v1/mcp-admin/tokens", None),
                               ("POST", "/api/v1/mcp-admin/tokens", {"name": "agent", "scope": "read"}),
                               ("DELETE", "/api/v1/mcp-admin/tokens/tok_x", None)):
        r = client.request(method, path, json=body, headers=bearer(secret))
        assert r.status_code == 403 and r.json()["detail"] == FORBIDDEN, (method, path, r.text)
    assert client.get("/api/v1/mcp-admin/tokens", headers=bearer(owner_jwt)).status_code == 200
    assert client.get("/api/v1/mcp-admin", headers=bearer(secret)).status_code == 200


def test_every_fence_prefix_still_matches_a_real_route():
    from src.main import app

    paths = [path for kind, path, _r, _i in _walk(app.routes) if kind == "http"]
    assert len(paths) > 100
    for prefix, family in fence.FENCED:
        assert any(fence._matches(p, prefix) for p in paths), (prefix, family)


def test_a_key_with_no_request_context_is_refused(key_store, live_key):
    import asyncio

    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from src.api.auth import require_auth

    _, secret = live_key
    with pytest.raises(HTTPException) as refused:
        asyncio.run(require_auth(HTTPAuthorizationCredentials(scheme="Bearer", credentials=secret)))
    assert refused.value.status_code == 403

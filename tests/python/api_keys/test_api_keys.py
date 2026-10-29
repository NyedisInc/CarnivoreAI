
from __future__ import annotations

import sqlite3

from src.core.api_keys import store as store_module
from tests.python.api_keys.conftest import bearer

NORMAL_ROUTE = "/api/v1/log-level"


def _create(client, owner_jwt: str, name: str = "crate sync") -> tuple[dict, str]:
    r = client.post("/api/v1/api-keys", json={"name": name}, headers=bearer(owner_jwt))
    assert r.status_code == 201, r.text
    body = r.json()
    return body["key"], body["secret"]


def test_a_created_key_authenticates_a_normal_route(client, owner_jwt, key_store):
    row, secret = _create(client, owner_jwt)
    assert secret.startswith("cak_") and len(secret) >= 4 + 43
    assert client.get(NORMAL_ROUTE).status_code == 401
    r = client.get(NORMAL_ROUTE, headers=bearer(secret))
    assert r.status_code == 200, r.text


def test_a_revoked_key_gets_401(client, owner_jwt, key_store):
    row, secret = _create(client, owner_jwt)
    assert client.get(NORMAL_ROUTE, headers=bearer(secret)).status_code == 200
    r = client.delete(f"/api/v1/api-keys/{row['id']}", headers=bearer(owner_jwt))
    assert r.status_code == 200 and r.json()["revoked"]["revoked_at"] is not None
    refused = client.get(NORMAL_ROUTE, headers=bearer(secret))
    assert refused.status_code == 401
    assert refused.json()["detail"]["reason"] == "api_key_invalid"


def test_a_garbage_key_gets_401(client, owner_jwt, key_store):
    _create(client, owner_jwt)
    for junk in ("cak_", "cak_not-a-real-key", "cak_" + "A" * 43):
        r = client.get(NORMAL_ROUTE, headers=bearer(junk))
        assert r.status_code == 401, (junk, r.text)


def test_unknown_revoke_is_404(client, owner_jwt, key_store):
    assert client.delete("/api/v1/api-keys/key_nope", headers=bearer(owner_jwt)).status_code == 404


def test_the_stored_row_holds_no_plaintext_key(client, owner_jwt, key_store, tmp_path):
    row, secret = _create(client, owner_jwt)
    path = tmp_path / store_module.DB_NAME
    raw = path.read_bytes()
    assert secret.encode() not in raw and secret[4:].encode() not in raw
    with sqlite3.connect(path) as conn:
        stored = conn.execute("SELECT * FROM api_keys").fetchall()
    assert len(stored) == 1
    assert all(secret not in str(cell) and secret[4:] not in str(cell) for cell in stored[0])
    assert store_module.hash_key(secret) in stored[0]
    assert (path.stat().st_mode & 0o777) == 0o600


def test_the_list_never_returns_a_secret(client, owner_jwt, key_store):
    _, first = _create(client, owner_jwt, "one")
    _, second = _create(client, owner_jwt, "two")
    r = client.get("/api/v1/api-keys", headers=bearer(owner_jwt))
    assert r.status_code == 200
    text = r.text
    for secret in (first, second):
        assert secret not in text and secret[4:] not in text and store_module.hash_key(secret) not in text
    keys = r.json()["keys"]
    assert {k["name"] for k in keys} == {"one", "two"}
    assert all(set(k) == {"id", "name", "display_prefix", "created_at", "last_used_at", "revoked_at"} for k in keys)
    assert all(k["display_prefix"].startswith("cak_") and len(k["display_prefix"]) == 4 + store_module.DISPLAY_CHARS for k in keys)


def test_last_used_moves_and_is_throttled(tmp_path):
    clock = [1000.0]
    store = store_module.ApiKeyStore(tmp_path / store_module.DB_NAME, clock=lambda: clock[0])
    row, secret = store.create("script")
    assert row["last_used_at"] is None
    assert store.authenticate(secret)["last_used_at"] == 1000.0
    clock[0] = 1010.0
    assert store.authenticate(secret)["last_used_at"] == 1000.0
    clock[0] = 1000.0 + store_module.USED_FLUSH_SECONDS
    assert store.authenticate(secret)["last_used_at"] == clock[0]
    assert store.list()[0]["last_used_at"] == clock[0]


def test_last_used_moves_through_a_real_request(client, owner_jwt, key_store):
    row, secret = _create(client, owner_jwt)
    assert client.get(NORMAL_ROUTE, headers=bearer(secret)).status_code == 200
    listed = client.get("/api/v1/api-keys", headers=bearer(owner_jwt)).json()["keys"]
    assert listed[0]["last_used_at"] is not None


def test_a_bad_name_is_422(client, owner_jwt, key_store):
    assert client.post("/api/v1/api-keys", json={"name": "   "}, headers=bearer(owner_jwt)).status_code == 422
    assert client.post("/api/v1/api-keys", json={"name": "x" * 61}, headers=bearer(owner_jwt)).status_code in (400, 422)


def test_a_symlinked_key_file_is_refused(tmp_path):
    target = tmp_path / "elsewhere.db"
    target.write_bytes(b"")
    link = tmp_path / store_module.DB_NAME
    link.symlink_to(target)
    store = store_module.ApiKeyStore(link)
    try:
        store.list()
    except store_module.ApiKeyStoreError:
        return
    raise AssertionError("a symlinked key file was opened")

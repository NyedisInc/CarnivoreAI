
import os
import tempfile
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_loaded_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_loaded_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

import src.api.auth as auth_mod  # noqa: E402
import src.api.enrollment_routes as enrollment_routes  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.api_keys import gate as api_key_gate, store as api_key_store  # noqa: E402
from src.core.owner_identity.otpauth import build_otpauth_uri  # noqa: E402

LOADED = "JBSWY3DPEHPK3PXP"
ROTATED = "KRSXG5CTMVRXEZLU"


ROUTE = "/api/v1/auth/enrollment/loaded"
PORT = settings.port


class Shim:

    def __init__(self, app, updates=None):
        self.app, self.updates = app, updates or {}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, **self.updates)
        await self.app(scope, receive, send)


@pytest.fixture()
def make_client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"agents": {}}')
    env_file = tmp_path / ".env"
    env_file.write_text(f"TOTP_SECRET={ROTATED}\n")
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    monkeypatch.setattr(settings, "totp_secret", LOADED)
    monkeypatch.setattr(settings, "jwt_secret", "test-jwt-secret-not-a-real-one-32b")
    monkeypatch.delenv("TOTP_SECRET", raising=False)
    monkeypatch.setattr(enrollment_routes, "env_file_path", lambda: env_file)
    monkeypatch.setattr(enrollment_routes, "computer_display_name", lambda: "Test Mac")
    keys = api_key_store.ApiKeyStore(tmp_path / api_key_store.DB_NAME)
    monkeypatch.setattr(api_key_gate, "get_store", lambda: keys)
    settings.drop_auth_config_cache()
    auth_mod.limiter.reset()
    app = FastAPI()
    app.state.limiter = auth_mod.limiter
    app.include_router(enrollment_routes.router, prefix="/api/v1")
    app.keys = keys

    def factory(client=("127.0.0.1", 50000), updates=None):
        return TestClient(Shim(app, updates), base_url=f"http://127.0.0.1:{PORT}", client=client)

    factory.keys = keys
    yield factory
    auth_mod.limiter.reset()
    settings.drop_auth_config_cache()


def _bearer() -> dict[str, str]:
    token, _ttl = auth_mod.create_access_token("owner")
    return {"Authorization": f"Bearer {token}"}


def _assert_refused(resp, status: int = 403, reason: str = "enrollment_local_only") -> None:
    assert resp.status_code == status, resp.text
    assert resp.json()["detail"]["reason"] == reason
    assert LOADED not in resp.text and ROTATED not in resp.text and "otpauth" not in resp.text


def test_requires_a_login_token(make_client):
    assert make_client().get(ROUTE).status_code == 401


def test_serves_the_loaded_secret_not_the_env_file(make_client):
    resp = make_client().get(ROUTE, headers=_bearer())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["otpauth_uri"] == build_otpauth_uri(LOADED, "Test Mac")
    assert ROTATED not in resp.text
    assert body["restart_pending"] is True
    assert "no-store" in resp.headers["cache-control"]


def test_no_restart_pending_when_env_matches(make_client, tmp_path):
    (tmp_path / ".env").write_text(f"TOTP_SECRET={LOADED}\n")
    assert make_client().get(ROUTE, headers=_bearer()).json()["restart_pending"] is False


@pytest.mark.parametrize("peer", [("192.168.1.20", 50000), ("10.0.0.5", 50000)])
def test_refuses_a_non_local_client(make_client, peer):
    _assert_refused(make_client(client=peer).get(ROUTE, headers=_bearer()))


@pytest.mark.parametrize("origin", [f"http://127.0.0.1:{PORT}", "http://evil.example"])
def test_refuses_any_origin_header(make_client, origin):
    _assert_refused(make_client().get(ROUTE, headers={**_bearer(), "Origin": origin}))


@pytest.mark.parametrize("site", ["same-origin", "none", "cross-site"])
def test_refuses_any_sec_fetch_site_header(make_client, site):
    _assert_refused(make_client().get(ROUTE, headers={**_bearer(), "Sec-Fetch-Site": site}))


def test_refuses_an_api_key(make_client):
    _row, secret = make_client.keys.create("tray test")
    resp = make_client().get(ROUTE, headers={"Authorization": f"Bearer {secret}"})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["reason"] == "api_key_forbidden"
    assert LOADED not in resp.text and "otpauth" not in resp.text


@pytest.mark.parametrize("tag", ["via_link", "via_peer_link"])
def test_refuses_a_link_tagged_request(make_client, tag):
    _assert_refused(make_client(updates={tag: True}).get(ROUTE, headers=_bearer()))


CODE_ROUTE = "/api/v1/auth/enrollment/loaded/code"


def test_code_route_is_the_loaded_secrets_code_never_the_env_files(make_client):
    resp = make_client().get(CODE_ROUTE, headers=_bearer())
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"code": None, "restart_pending": True}
    assert LOADED not in resp.text and ROTATED not in resp.text and "otpauth" not in resp.text


def test_code_route_serves_a_code_the_server_accepts(make_client, tmp_path):
    import pyotp

    (tmp_path / ".env").write_text(f"TOTP_SECRET={LOADED}\n")
    resp = make_client().get(CODE_ROUTE, headers=_bearer())
    body = resp.json()
    assert resp.status_code == 200 and body["restart_pending"] is False
    assert pyotp.TOTP(LOADED).verify(body["code"], valid_window=1)
    assert "no-store" in resp.headers["cache-control"]
    assert LOADED not in resp.text


def test_code_route_keeps_the_loaded_routes_fences(make_client):
    assert make_client().get(CODE_ROUTE).status_code == 401
    _assert_refused(make_client(client=("192.168.1.20", 50000)).get(CODE_ROUTE, headers=_bearer()))
    _assert_refused(make_client().get(CODE_ROUTE, headers={**_bearer(), "Origin": f"http://127.0.0.1:{PORT}"}))


def _match_env(tmp_path) -> None:
    (tmp_path / ".env").write_text(f"TOTP_SECRET={LOADED}\n")


def test_code_route_skips_a_code_the_login_just_spent(make_client, tmp_path):
    import pyotp

    _match_env(tmp_path)
    spent = pyotp.TOTP(LOADED).now()
    auth_mod._totp_seen_cache[spent] = 0.0
    try:
        code = make_client().get(CODE_ROUTE, headers=_bearer()).json()["code"]
        assert code not in auth_mod._totp_seen_cache, "a replayed code would be refused as code_reused"
        assert pyotp.TOTP(LOADED).verify(code, valid_window=1)
    finally:
        auth_mod._totp_seen_cache.clear()


def test_code_route_serves_no_code_when_both_steps_are_spent(make_client, tmp_path):
    import pyotp

    _match_env(tmp_path)
    totp = pyotp.TOTP(LOADED)
    auth_mod._totp_seen_cache[totp.now()] = 0.0
    auth_mod._totp_seen_cache[totp.at(time.time() + 30)] = 0.0
    try:
        body = make_client().get(CODE_ROUTE, headers=_bearer()).json()
        assert body == {"code": None, "restart_pending": False}
    finally:
        auth_mod._totp_seen_cache.clear()


def test_code_route_never_logs_the_code(make_client, tmp_path, caplog):
    import logging

    _match_env(tmp_path)
    with caplog.at_level(logging.DEBUG):
        code = make_client().get(CODE_ROUTE, headers=_bearer()).json()["code"]
    assert code
    logged = caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    assert code not in logged and LOADED not in logged and ROTATED not in logged


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-origin"},
        {"X-Forwarded-For": "203.0.113.9"},
        {"Forwarded": "for=203.0.113.9"},
        {"Host": "evil.example"},
        {"Host": f"192.168.1.5:{PORT}"},
    ],
)
def test_code_route_refuses_a_browser_forwarded_or_wrong_host(make_client, headers):
    _assert_refused(make_client().get(CODE_ROUTE, headers={**_bearer(), **headers}))


def test_code_route_refuses_a_peer_link_request(make_client):
    _assert_refused(make_client(updates={"via_peer_link": True}).get(CODE_ROUTE, headers=_bearer()))


def test_code_route_refuses_an_api_key(make_client):
    _row, secret = make_client.keys.create("tray code test")
    resp = make_client().get(CODE_ROUTE, headers={"Authorization": f"Bearer {secret}"})
    assert resp.status_code == 403 and resp.json()["detail"]["reason"] == "api_key_forbidden"
    assert "code" not in resp.json()

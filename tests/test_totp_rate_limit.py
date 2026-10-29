from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pyotp
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TOTP_SECRET = pyotp.random_base32()
JWT_SECRET = "test-secret-for-totp-rate-limit"


def _make_fake_auth_config(trust_proxy: bool = False, per_minute: int = 5, per_hour: int = 20):
    rate_limits = SimpleNamespace(
        totp_verify_per_minute=per_minute,
        totp_verify_per_hour=per_hour,
        trust_proxy_headers=trust_proxy,
    )
    return SimpleNamespace(
        totp_secret=TOTP_SECRET,
        jwt_secret=JWT_SECRET,
        jwt_expiry_minutes=30,
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=604800,
        refresh_grace_seconds=10,
        auth_rate_limits=rate_limits,
    )


@pytest.fixture
def reset_state():
    import src.api.auth as auth_mod

    auth_mod._totp_seen_cache.clear()
    auth_mod.limiter.reset()

    yield

    auth_mod._totp_seen_cache.clear()
    auth_mod.limiter.reset()


@pytest.fixture
def patched_auth(monkeypatch, reset_state):
    fake = _make_fake_auth_config()

    import src.api.auth as auth_mod
    from src.config import settings as real_settings

    def fake_loader(self=None):
        return fake

    monkeypatch.setattr(type(real_settings), "load_auth_config", fake_loader)
    return fake


@pytest.fixture
def client(patched_auth):
    from src.api.auth import limiter
    from src.api.auth_routes import router as auth_router

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(auth_router, prefix="/api/v1")
    return TestClient(app)


@pytest.fixture
def client_trust_proxy(monkeypatch, reset_state):
    fake = _make_fake_auth_config(trust_proxy=True)

    import src.api.auth as auth_mod
    from src.config import settings as real_settings

    def fake_loader(self=None):
        return fake

    monkeypatch.setattr(type(real_settings), "load_auth_config", fake_loader)

    from src.api.auth import limiter
    from src.api.auth_routes import router as auth_router

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(auth_router, prefix="/api/v1")
    return TestClient(app)


def _mint_codes_distinct(n: int) -> list[str]:
    import random
    seen = set()
    out = []
    while len(out) < n:
        c = f"{random.randint(0, 999999):06d}"
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def test_sixth_request_hits_429_with_retry_after(client):
    codes = _mint_codes_distinct(6)

    responses = []
    for code in codes:
        r = client.post("/api/v1/auth/verify", json={"code": code})
        responses.append(r)

    for r in responses[:5]:
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    assert responses[5].status_code == 429, (
        f"expected 429 on 6th request, got {responses[5].status_code}: {responses[5].text}"
    )
    assert "retry-after" in {k.lower() for k in responses[5].headers.keys()}, (
        f"429 response missing Retry-After header: {dict(responses[5].headers)}"
    )


def test_valid_code_replay_rejected_as_code_reused(client):
    totp = pyotp.TOTP(TOTP_SECRET)
    code = totp.now()

    r1 = client.post("/api/v1/auth/verify", json={"code": code})
    assert r1.status_code == 200, f"first submit should succeed, got {r1.status_code}: {r1.text}"
    assert "token" in r1.json() or "access_token" in r1.json()

    r2 = client.post("/api/v1/auth/verify", json={"code": code})
    assert r2.status_code == 401, f"replay should be 401, got {r2.status_code}: {r2.text}"

    body = r2.json()
    detail = body.get("detail", body)
    if isinstance(detail, dict):
        assert detail.get("reason") == "code_reused", f"unexpected reason: {detail}"
    else:
        pytest.fail(f"expected structured detail dict with reason=code_reused, got: {body}")


def test_cache_expiry_allows_fresh_code(client):
    import src.api.auth as auth_mod

    totp = pyotp.TOTP(TOTP_SECRET)
    code1 = totp.now()

    r1 = client.post("/api/v1/auth/verify", json={"code": code1})
    assert r1.status_code == 200, r1.text

    auth_mod._totp_seen_cache.clear()

    r2 = client.post("/api/v1/auth/verify", json={"code": code1})
    assert r2.status_code == 200, f"post-expiry re-submit should succeed, got {r2.status_code}: {r2.text}"


def test_trust_proxy_headers_independent_counters(client_trust_proxy):
    codes_a = _mint_codes_distinct(6)
    codes_b = _mint_codes_distinct(6)

    for code in codes_a[:5]:
        r = client_trust_proxy.post(
            "/api/v1/auth/verify",
            json={"code": code},
            headers={"X-Forwarded-For": "203.0.113.16"},
        )
        assert r.status_code == 401, r.text

    r_a_blocked = client_trust_proxy.post(
        "/api/v1/auth/verify",
        json={"code": codes_a[5]},
        headers={"X-Forwarded-For": "203.0.113.16"},
    )
    assert r_a_blocked.status_code == 429, r_a_blocked.text

    for code in codes_b[:5]:
        r = client_trust_proxy.post(
            "/api/v1/auth/verify",
            json={"code": code},
            headers={"X-Forwarded-For": "192.0.2.14"},
        )
        assert r.status_code == 401, f"client B should have fresh budget, got {r.status_code}: {r.text}"

    r_b_blocked = client_trust_proxy.post(
        "/api/v1/auth/verify",
        json={"code": codes_b[5]},
        headers={"X-Forwarded-For": "192.0.2.14"},
    )
    assert r_b_blocked.status_code == 429, r_b_blocked.text


def test_xff_ignored_when_trust_proxy_false(client):
    codes = _mint_codes_distinct(6)
    responses = []
    for i, code in enumerate(codes):
        r = client.post(
            "/api/v1/auth/verify",
            json={"code": code},
            headers={"X-Forwarded-For": f"10.0.0.{i + 1}"},
        )
        responses.append(r)

    assert responses[5].status_code == 429, (
        f"XFF should be ignored when trust_proxy_headers=False; "
        f"6th status: {responses[5].status_code}"
    )

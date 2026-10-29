from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jwt as pyjwt
import pyotp
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


TOTP_SECRET = pyotp.random_base32()
JWT_SECRET = "test-secret-for-refresh-tokens"


def _make_fake_auth_config():
    rate_limits = SimpleNamespace(
        totp_verify_per_minute=1000,
        totp_verify_per_hour=10000,
        trust_proxy_headers=False,
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
    from src.config import settings as real_settings

    def fake_loader(self=None):
        return fake

    monkeypatch.setattr(type(real_settings), "load_auth_config", fake_loader)
    return fake


@pytest_asyncio.fixture
async def refresh_store(tmp_path):
    from src.core.refresh_store import RefreshStore

    store = RefreshStore(str(tmp_path / "refresh.db"))
    await store.init()
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture
def client(patched_auth, refresh_store):
    from src.api.auth import limiter
    from src.api.auth_routes import router as auth_router

    app = FastAPI()
    app.state.limiter = limiter
    app.state.refresh_store = refresh_store
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(auth_router, prefix="/api/v1")
    return TestClient(app)


def _login(client: TestClient) -> dict:
    totp = pyotp.TOTP(TOTP_SECRET)
    code = totp.now()
    r = client.post("/api/v1/auth/verify", json={"code": code})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()


def _refresh(client: TestClient, refresh_token: str):
    return client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )


def test_login_mints_access_and_refresh_pair(client):
    body = _login(client)
    assert body["success"] is True
    assert "access_token" in body and body["access_token"]
    assert "refresh_token" in body and body["refresh_token"]
    assert body.get("token") == body["access_token"], (
        "deprecated `token` alias must equal `access_token`"
    )
    assert isinstance(body["expires_in"], int) and body["expires_in"] > 0


def test_access_token_has_typ_access(client):
    body = _login(client)
    claims = pyjwt.decode(body["access_token"], JWT_SECRET, algorithms=["HS256"])
    assert claims["typ"] == "access"


def test_refresh_token_has_typ_refresh_and_jti(client):
    body = _login(client)
    claims = pyjwt.decode(body["refresh_token"], JWT_SECRET, algorithms=["HS256"])
    assert claims["typ"] == "refresh"
    assert claims.get("jti"), "refresh token must carry a jti"


def test_refresh_rotates_and_old_is_superseded(client, refresh_store):
    body = _login(client)
    old_refresh = body["refresh_token"]
    old_claims = pyjwt.decode(old_refresh, JWT_SECRET, algorithms=["HS256"])
    old_jti = old_claims["jti"]

    r = _refresh(client, old_refresh)
    assert r.status_code == 200, r.text
    new_body = r.json()

    new_refresh_claims = pyjwt.decode(
        new_body["refresh_token"], JWT_SECRET, algorithms=["HS256"]
    )
    assert new_refresh_claims["jti"] != old_jti, (
        "new refresh must have a different jti"
    )

    assert pytest_run(refresh_store.is_superseded(old_jti)) is True


def test_refresh_within_grace_succeeds(client, refresh_store):
    body = _login(client)
    old_claims = pyjwt.decode(body["refresh_token"], JWT_SECRET, algorithms=["HS256"])
    old_jti = old_claims["jti"]

    r = _refresh(client, body["refresh_token"])
    assert r.status_code == 200, r.text

    still_valid = pytest_run(refresh_store.is_valid(old_jti, grace_seconds=10))
    assert still_valid is True, (
        "within grace window, just-rotated refresh jti must still be valid"
    )


def test_refresh_reuse_after_grace_burns_chain(client, refresh_store):
    body = _login(client)
    old_refresh = body["refresh_token"]
    old_claims = pyjwt.decode(old_refresh, JWT_SECRET, algorithms=["HS256"])
    old_jti = old_claims["jti"]

    r1 = _refresh(client, old_refresh)
    assert r1.status_code == 200, r1.text
    new_refresh_claims = pyjwt.decode(
        r1.json()["refresh_token"], JWT_SECRET, algorithms=["HS256"]
    )
    new_jti = new_refresh_claims["jti"]

    async def _age_out():
        import aiosqlite
        async with aiosqlite.connect(refresh_store._db_path) as db:
            await db.execute(
                "UPDATE refresh_tokens SET superseded_at = ? WHERE jti = ?",
                (int(time.time()) - 60, old_jti),
            )
            await db.commit()

    pytest_run(_age_out())

    r2 = _refresh(client, old_refresh)
    assert r2.status_code == 401, r2.text

    async def _check():
        async with asyncio.Lock():
            pass
        import aiosqlite
        async with aiosqlite.connect(refresh_store._db_path) as db:
            cur = await db.execute(
                "SELECT jti, revoked FROM refresh_tokens WHERE jti IN (?, ?)",
                (old_jti, new_jti),
            )
            rows = await cur.fetchall()
            await cur.close()
            return rows

    rows = pytest_run(_check())
    statuses = {r[0]: r[1] for r in rows}
    assert statuses[old_jti] == 1, "old jti must be revoked"
    assert statuses[new_jti] == 1, "descendant jti must be revoked (chain)"


def test_refresh_with_explicitly_revoked_token_rejected(client, refresh_store):
    body = _login(client)
    claims = pyjwt.decode(body["refresh_token"], JWT_SECRET, algorithms=["HS256"])
    jti = claims["jti"]

    pytest_run(refresh_store.revoke(jti))

    r = _refresh(client, body["refresh_token"])
    assert r.status_code == 401, r.text


def test_refresh_token_rejected_on_protected_endpoint(client):
    body = _login(client)
    r = client.get(
        "/api/v1/auth/status",
        headers={"Authorization": f"Bearer {body['refresh_token']}"},
    )
    assert r.status_code == 401, r.text


def test_access_token_accepted_on_protected_endpoint(client):
    body = _login(client)
    r = client.get(
        "/api/v1/auth/status",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert r.status_code == 200, r.text


def test_logout_revokes_refresh(client, refresh_store):
    body = _login(client)
    claims = pyjwt.decode(body["refresh_token"], JWT_SECRET, algorithms=["HS256"])
    jti = claims["jti"]

    r = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": body["refresh_token"]},
    )
    assert r.status_code == 200, r.text

    r2 = _refresh(client, body["refresh_token"])
    assert r2.status_code == 401


def test_purge_expired_removes_old_rows(refresh_store):
    async def _run():
        import aiosqlite
        now = int(time.time())
        ancient = now - (2 * 86400)
        recent = now - 30
        future = now + 3600

        async with aiosqlite.connect(refresh_store._db_path) as db:
            await db.execute(
                "INSERT INTO refresh_tokens (jti, user, exp) VALUES (?, ?, ?)",
                ("ancient", "u", ancient),
            )
            await db.execute(
                "INSERT INTO refresh_tokens (jti, user, exp) VALUES (?, ?, ?)",
                ("recent", "u", recent),
            )
            await db.execute(
                "INSERT INTO refresh_tokens (jti, user, exp) VALUES (?, ?, ?)",
                ("future", "u", future),
            )
            await db.commit()

        deleted = await refresh_store.purge_expired()
        jtis = await refresh_store._all_jtis()
        return deleted, set(jtis)

    deleted, remaining = pytest_run(_run())
    assert deleted >= 1
    assert "ancient" not in remaining
    assert "recent" in remaining
    assert "future" in remaining


def test_refresh_with_access_token_rejected(client):
    body = _login(client)
    r = _refresh(client, body["access_token"])
    assert r.status_code == 401, r.text


def test_lost_race_within_grace_gets_the_winners_pair(client):
    old = _login(client)["refresh_token"]
    first = _refresh(client, old)
    assert first.status_code == 200, first.text
    second = _refresh(client, old)
    assert second.status_code == 200, second.text
    assert second.json()["refresh_token"] == first.json()["refresh_token"]
    assert second.json()["access_token"] == first.json()["access_token"]
    third = _refresh(client, first.json()["refresh_token"])
    assert third.status_code == 200, third.text


def test_concurrent_refreshes_all_get_one_pair(patched_auth, reset_state, tmp_path):
    import httpx
    from src.api.auth import limiter
    from src.api.auth_routes import router as auth_router
    from src.core.refresh_store import RefreshStore

    async def _run() -> list:
        store = RefreshStore(str(tmp_path / "race.db"))
        await store.init()
        app = FastAPI()
        app.state.limiter = limiter
        app.state.refresh_store = store
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)
        app.include_router(auth_router, prefix="/api/v1")
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
                code = pyotp.TOTP(TOTP_SECRET).now()
                login = await http.post("/api/v1/auth/verify", json={"code": code})
                token = login.json()["refresh_token"]
                return await asyncio.gather(*[
                    http.post("/api/v1/auth/refresh", json={"refresh_token": token})
                    for _ in range(5)
                ])
        finally:
            await store.close()

    answers = pytest_run(_run())
    assert [a.status_code for a in answers] == [200] * 5, [a.text for a in answers]
    assert len({a.json()["refresh_token"] for a in answers}) == 1


def test_lost_race_replay_refused_once_the_descendant_is_revoked(client):
    old = _login(client)["refresh_token"]
    first = _refresh(client, old)
    assert first.status_code == 200, first.text
    out = client.post("/api/v1/auth/logout", json={"refresh_token": first.json()["refresh_token"]})
    assert out.status_code == 200, out.text
    assert _refresh(client, old).status_code == 401


def test_rotation_replay_cache_forgets_after_its_ttl():
    from src.core.refresh_rotation.replay import RotatedPair, RotationReplayCache

    now = [1000.0]
    cache = RotationReplayCache(clock=lambda: now[0])
    pair = RotatedPair(access_token="a", refresh_token="r", refresh_jti="j", access_expires_at=5000.0)
    cache.remember("old", pair, ttl_seconds=10)
    assert cache.recall("old") == pair
    now[0] += 10
    assert cache.recall("old") is None


def pytest_run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, loop).result()
    except RuntimeError:
        pass
    return asyncio.new_event_loop().run_until_complete(coro)

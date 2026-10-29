
import httpx
import pytest

from tests.phone_link.pairing_helpers import pair_device
from fastapi import FastAPI, HTTPException

from src.api import account_gates
from src.api import phone_link_routes as routes
from src.api.auth import limiter, require_auth
from src.config.relay import RelayConfig
from src.core.phone_link.gate import COOKIE_NAME, PENDING_COOKIE_NAME
from src.core.phone_link.manager import PhoneLinkManager
from src.api import web_push_routes
from src.core.phone_link.pairing import PairingStore
from src.core.web_push.sender import PushSender


class _Tunnel:
    status = "connected"

    def close_device(self, device_id):
        pass


class Manager(PhoneLinkManager):

    started = stopped = 0

    async def _start(self):
        self.started += 1
        self._tunnel = _Tunnel()

    async def _stop(self):
        self.stopped += 1
        self._tunnel = None
        self._listener = None


@pytest.fixture
def mgr(tmp_path):
    m = Manager(app=None, config=RelayConfig(), state_dir=tmp_path, db_path=tmp_path / "c.db", version="1.0.0")
    m.hostname = "abcdefghijklmnopqrstuvwxyz.link.carnivore.ai"
    limiter.reset()
    yield m
    m.pairing.close()


def make_app(manager, via_link=False, device=None, link_host=None):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.include_router(routes.pair_router)
    app.include_router(web_push_routes.router, prefix="/api/v1")
    app.state.phone_link = manager
    app.state.limiter = limiter
    app.state.web_push_sender = PushSender(manager._state_dir, manager._state_dir / "config.json")
    app.dependency_overrides[require_auth] = lambda: True
    app.dependency_overrides[routes._gate_enable] = lambda: None
    app.dependency_overrides[account_gates.require_account("phone_pairing")] = lambda: None

    async def tag(scope, receive, send, inner=app):
        if scope["type"] == "http":
            if via_link:
                scope["via_link"] = True
                scope["client"] = ("203.0.113.9", 5000)
                scope["link_host"] = link_host or manager.hostname
            if device:
                scope["link_device"] = device
        await inner(scope, receive, send)

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=tag), base_url="https://x.test")


@pytest.mark.asyncio
async def test_the_lifecycle_runs_only_while_enabled_and_a_phone_or_window_exists(mgr):
    await mgr.reconcile()
    assert mgr.started == 0
    mgr.pairing.open_window()
    await mgr.reconcile()
    assert mgr.started == 0
    await mgr.set_enabled(True)
    assert mgr.started == 1 and mgr.status()["running"]
    mgr.pairing.close_window()
    await mgr.reconcile()
    assert mgr.stopped == 1
    cookie = pair_device(mgr.pairing, "203.0.113.5")
    await mgr.reconcile()
    assert mgr.started == 2
    await mgr.revoke(mgr.pairing.device_for_cookie(cookie))
    assert mgr.stopped == 2 and not mgr.status()["running"]


@pytest.mark.asyncio
async def test_relay_disabled_kills_everything(tmp_path):
    m = Manager(app=None, config=RelayConfig(enabled=False), state_dir=tmp_path, db_path=tmp_path / "c.db", version="1")
    m.pairing.set_enabled(True)
    m.pairing.open_window()
    await m.reconcile()
    assert m.started == 0 and m.wanted() is False
    async with make_app(m) as c:
        assert (await c.get("/api/v1/phone-link")).status_code == 503
    m.pairing.close()


@pytest.mark.asyncio
async def test_owner_routes_switch_devices_and_refuse_the_link(mgr):
    async with make_app(mgr) as c:
        assert (await c.get("/api/v1/phone-link")).json()["enabled"] is False
        assert (await c.post("/api/v1/phone-link/pairing-window")).status_code == 409
        assert (await c.put("/api/v1/phone-link", json={"enabled": True})).json()["enabled"] is True
        body = (await c.post("/api/v1/phone-link/pairing-window")).json()
        assert body["url"].startswith(f"https://{mgr.hostname}/pair#") and len(body["code"]) == 8
        assert body["qr"].startswith("data:image/png;base64,")
        assert set(body) == {"url", "pair_url", "code", "expires_at", "qr", "qr_expires_at", "qr_rotate_seconds"}
        assert body["pair_url"] == f"https://{mgr.hostname}/pair" and body["qr_rotate_seconds"] == 60
        assert (await c.get("/api/v1/phone-link")).json()["pairing"] == {"state": "open", "device": None, "locked": False}
        rotated = (await c.post("/api/v1/phone-link/pairing-window/qr")).json()
        assert set(rotated) == {"url", "qr", "qr_expires_at"} and rotated["url"] != body["url"]
        handle = mgr.pairing.claim_code(body["code"], "203.0.113.5").handle
        assert (await c.get("/api/v1/phone-link")).json()["pairing"] == {"state": "pending", "device": None, "locked": False}
        assert (await c.get("/api/v1/phone-link/devices")).json() == []
        cookie = mgr.pairing.complete_pending(handle)
        claimed = (await c.get("/api/v1/phone-link")).json()["pairing"]
        assert claimed["state"] == "claimed" and claimed["device"]["kind"] == "browser"
        (device,) = (await c.get("/api/v1/phone-link/devices")).json()
        assert set(device) == {"id", "label", "kind", "created_at", "last_seen", "push"}
        assert device["push"] == [] and device["last_seen"] is None
        assert (await c.delete("/api/v1/phone-link/devices/nope")).status_code == 404
        assert (await c.delete(f"/api/v1/phone-link/devices/{device['id']}")).json() == {"revoked": True}
        assert mgr.pairing.device_for_cookie(cookie) is None
    async with make_app(mgr, via_link=True) as c:
        for method, path in (("GET", "/api/v1/phone-link"), ("PUT", "/api/v1/phone-link"),
                             ("POST", "/api/v1/phone-link/pairing-window"),
                             ("POST", "/api/v1/phone-link/pairing-window/qr"),
                             ("DELETE", "/api/v1/phone-link/pairing-window"),
                             ("GET", "/api/v1/phone-link/devices"), ("DELETE", "/api/v1/phone-link/devices/x")):
            assert (await c.request(method, path, json={"enabled": False})).status_code == 403, path


@pytest.mark.asyncio
async def test_the_pair_routes_exist_only_through_the_link_and_set_a_host_cookie(mgr):
    await mgr.set_enabled(True)
    window = mgr.pairing.open_window()
    async with make_app(mgr) as c:
        for path in ("/pair", "/pair/pair.js"):
            assert (await c.get(path)).status_code == 404
        assert (await c.post("/pair/claim", json={"secret": window.secret})).status_code == 404
    async with make_app(mgr, via_link=True) as c:
        page = await c.get("/pair")
        assert page.status_code == 200 and "<script>" not in page.text
        assert 'src="/static/dist/pair.js"' in page.text and 'href="/static/dist/pair.css"' in page.text
        assert (await c.get("/pair/pair.js")).status_code == 404
        assert page.headers["referrer-policy"] == "no-referrer"
        assert (await c.post("/pair/claim", json={"secret": "wrong"})).status_code == 403
        ok = await c.post("/pair/claim", json={"secret": window.secret, "label": "iphone"})
        assert ok.status_code == 200 and ok.json() == {"ok": True, "status": "pending"}
        cookie = ok.headers["set-cookie"]
        for attr in (f"{PENDING_COOKIE_NAME}=", "HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=300"):
            assert attr in cookie, attr
        assert COOKIE_NAME not in cookie and "Domain" not in cookie
        assert mgr.pairing.device_count() == 0 and mgr.wanted()


class _Tokens:
    access_token, refresh_token = "access.jwt", "refresh.jwt"


def _fake_totp(monkeypatch, good="123456"):
    calls = []

    async def redeem(request, code):
        calls.append(code)
        if code != good:
            raise HTTPException(status_code=401, detail="Invalid authentication code")
        return _Tokens()

    monkeypatch.setattr(routes, "redeem_totp_code", redeem)
    return calls


@pytest.mark.asyncio
async def test_the_code_completes_the_pairing_in_one_step(mgr, monkeypatch):
    _fake_totp(monkeypatch)
    await mgr.set_enabled(True)
    window = mgr.pairing.open_window()
    async with make_app(mgr, via_link=True) as c:
        scan = await c.post("/pair/claim", json={"secret": window.secret, "label": "iphone"})
        pending = scan.headers["set-cookie"].split(";")[0]
        assert (await c.get("/pair/status", headers={"cookie": pending})).json() == {"paired": False, "pending": True}
        wrong = await c.post("/pair/verify", json={"code": "000000"}, headers={"cookie": pending})
        assert wrong.status_code == 401 and mgr.pairing.device_count() == 0 and "set-cookie" not in wrong.headers
        ok = await c.post("/pair/verify", json={"code": "123456"}, headers={"cookie": pending})
        assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"
        assert ok.json() == {"ok": True, "status": "paired", "access_token": "access.jwt", "refresh_token": "refresh.jwt"}
        cookies = ok.headers.get_list("set-cookie")
        device = next(v for v in cookies if v.startswith(COOKIE_NAME + "="))
        for attr in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age="):
            assert attr in device, attr
        assert "Domain" not in device
        assert any(v.startswith(PENDING_COOKIE_NAME + '="";') or v.startswith(PENDING_COOKIE_NAME + "=;") for v in cookies)
        assert mgr.pairing.device_count() == 1 and [d.label for d in mgr.pairing.devices()] == ["iphone"]
        again = await c.post("/pair/verify", json={"code": "123456"}, headers={"cookie": pending})
        assert again.status_code == 403 and again.json()["detail"] == "no_pending"


@pytest.mark.asyncio
async def test_five_wrong_codes_kill_the_pending_pairing(mgr, monkeypatch):
    calls = _fake_totp(monkeypatch)
    await mgr.set_enabled(True)
    window = mgr.pairing.open_window()
    async with make_app(mgr, via_link=True) as c:
        pending = (await c.post("/pair/claim", json={"secret": window.secret})).headers["set-cookie"].split(";")[0]
        codes = [(await c.post("/pair/verify", json={"code": "00000%d" % n}, headers={"cookie": pending})) for n in range(5)]
        assert [r.status_code for r in codes] == [401, 401, 401, 401, 403] and codes[-1].json()["detail"] == "pairing_dead"
        limiter.reset()
        right = await c.post("/pair/verify", json={"code": "123456"}, headers={"cookie": pending})
        assert right.status_code == 403 and len(calls) == 5
        assert mgr.pairing.device_count() == 0 and mgr.pairing.pairing_view()["state"] == "failed"
    async with make_app(mgr, via_link=True) as fresh:
        nobody = await fresh.post("/pair/verify", json={"code": "123456"})
        assert nobody.status_code == 403 and nobody.json()["detail"] == "no_pending" and len(calls) == 5


@pytest.mark.asyncio
async def test_pair_status_follows_the_cookie_and_its_host_and_a_paired_phone_is_already_paired(mgr):
    await mgr.set_enabled(True)
    jar = f"{COOKIE_NAME}={pair_device(mgr.pairing, '203.0.113.5', host=mgr.hostname)}"
    window = mgr.pairing.open_window()
    async with make_app(mgr, via_link=True) as c:
        assert (await c.get("/pair/status")).json() == {"paired": False, "pending": False}
        status = await c.get("/pair/status", headers={"cookie": jar})
        assert status.json() == {"paired": True, "pending": False} and status.headers["cache-control"] == "no-store"
        async with make_app(mgr, via_link=True, link_host="sync.example.com") as other:
            assert (await other.get("/pair/status", headers={"cookie": jar})).json()["paired"] is False
        again = await c.post("/pair/claim", json={"secret": window.secret}, headers={"cookie": jar})
        assert again.status_code == 200 and again.json()["status"] == "already_paired" and "set-cookie" not in again.headers
        assert mgr.pairing.device_count() == 1 and mgr.pairing.window_open()


@pytest.mark.asyncio
async def test_the_claim_posts_need_json_and_a_same_origin_when_one_is_sent(mgr):
    await mgr.set_enabled(True)
    window = mgr.pairing.open_window()
    async with make_app(mgr, via_link=True) as c:
        body = '{"secret": "%s"}' % window.secret
        assert (await c.post("/pair/claim", content=body)).status_code == 415
        assert (await c.post("/pair/claim", content=body, headers={"content-type": "text/plain"})).status_code == 415
        evil = await c.post("/pair/claim", json={"secret": window.secret}, headers={"origin": "https://evil.example"})
        assert evil.status_code == 403 and evil.json()["detail"] == "bad_origin"
        assert (await c.post("/pair/code", json={"code": window.code}, headers={"origin": "https://evil.example"})).status_code == 403
        assert mgr.pairing.device_count() == 0 and mgr.pairing.window_open()


@pytest.mark.asyncio
async def test_closing_and_rotating_the_window_over_the_owner_api(mgr):
    await mgr.set_enabled(True)
    async with make_app(mgr) as c:
        none = await c.post("/api/v1/phone-link/pairing-window/qr")
        assert none.status_code == 409 and none.json()["code"] == "no_window"
        await c.post("/api/v1/phone-link/pairing-window")
        assert mgr.pairing.window_open()
        assert (await c.delete("/api/v1/phone-link/pairing-window")).json() == {"closed": True}
        assert (await c.delete("/api/v1/phone-link/pairing-window")).json() == {"closed": True}
        assert not mgr.pairing.window_open()


@pytest.mark.asyncio
async def test_a_guesser_is_throttled_by_real_address(mgr):
    await mgr.set_enabled(True)
    mgr.pairing.open_window()
    async with make_app(mgr, via_link=True) as c:
        codes = [(await c.post("/pair/code", json={"code": "WRONG%03d" % n})).status_code for n in range(12)]
    assert codes[:10] == [403] * 10 and codes[10:] == [429, 429]


def _subscription_keys():
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    point = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda raw: __import__("base64").urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    return {"p256dh": b64(point), "auth": b64(os.urandom(16))}


PUSH_BODY = {"endpoint": "https://web.push.apple.com/abc", "keys": _subscription_keys()}


@pytest.mark.asyncio
async def test_a_subscription_made_over_the_link_is_bound_to_the_verified_device_and_a_revoke_removes_it(mgr):
    cookie = pair_device(mgr.pairing, "203.0.113.5", "iphone")
    device_id = mgr.pairing.device_for_cookie(cookie)
    async with make_app(mgr, via_link=True, device=device_id) as phone:
        forged = {**PUSH_BODY, "device_id": "someone-else"}
        made = await phone.post("/api/v1/push/subscriptions", json=forged)
        assert made.status_code == 201 and made.json()["device_id"] == device_id
    async with make_app(mgr) as mac:
        other = {**PUSH_BODY, "endpoint": "https://web.push.apple.com/mac"}
        assert (await mac.post("/api/v1/push/subscriptions", json=other)).json()["device_id"] is None
        (device,) = (await mac.get("/api/v1/phone-link/devices")).json()
        assert [p["service"] for p in device["push"]] == ["web.push.apple.com"] and device["push"][0]["last_result"] is None
        assert (await mac.delete(f"/api/v1/phone-link/devices/{device_id}")).status_code == 200
        left = (await mac.get("/api/v1/push/subscriptions")).json()["subscriptions"]
        assert [r["device_id"] for r in left] == [None]
        assert mgr.pairing.device_for_cookie(cookie) is None


@pytest.mark.asyncio
async def test_a_device_the_owner_never_paired_gets_no_device_from_a_non_link_request(mgr):
    async with make_app(mgr, device="dev") as c:
        assert (await c.post("/api/v1/push/subscriptions", json=PUSH_BODY)).json()["device_id"] is None


@pytest.mark.asyncio
async def test_status_carries_the_certificate_and_last_seen_is_recorded(mgr):
    async with make_app(mgr) as c:
        assert (await c.get("/api/v1/phone-link")).json()["cert"] is None
    cookie = pair_device(mgr.pairing, "203.0.113.5")
    mgr.pairing.touch(mgr.pairing.device_for_cookie(cookie))
    assert mgr.pairing.devices()[0].last_seen is not None


@pytest.mark.asyncio
async def test_a_subscribe_that_lost_the_race_with_a_revoke_is_undone_and_refused(mgr):
    async with make_app(mgr, via_link=True, device="revoked-mid-flight") as phone:
        assert (await phone.post("/api/v1/push/subscriptions", json=PUSH_BODY)).status_code == 403
    async with make_app(mgr) as mac:
        assert (await mac.get("/api/v1/push/subscriptions")).json()["subscriptions"] == []


@pytest.mark.asyncio
async def test_a_revoke_retry_after_the_device_is_gone_still_removes_its_subscriptions(mgr):
    cookie = pair_device(mgr.pairing, "203.0.113.5", "iphone")
    device_id = mgr.pairing.device_for_cookie(cookie)
    async with make_app(mgr, via_link=True, device=device_id) as phone:
        assert (await phone.post("/api/v1/push/subscriptions", json=PUSH_BODY)).status_code == 201
    mgr.pairing.revoke(device_id)
    async with make_app(mgr) as mac:
        assert (await mac.delete(f"/api/v1/phone-link/devices/{device_id}")).status_code == 404
        assert (await mac.get("/api/v1/push/subscriptions")).json()["subscriptions"] == []


@pytest.mark.asyncio
async def test_a_failing_touch_is_swallowed_and_logged(mgr):
    import sqlite3

    cookie = pair_device(mgr.pairing, "203.0.113.5")
    device_id = mgr.pairing.device_for_cookie(cookie)

    class Broken:
        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

    real, mgr.pairing._db = mgr.pairing._db, Broken()
    try:
        mgr.pairing.touch(device_id)
    finally:
        mgr.pairing._db = real


async def _dead_pairing(c, mgr):
    w = mgr.pairing.open_window()
    pending = (await c.post("/pair/claim", json={"secret": w.secret})).headers["set-cookie"].split(";")[0]
    for n in range(5):
        await c.post("/pair/verify", json={"code": "00000%d" % n}, headers={"cookie": pending})
    limiter.reset()


@pytest.mark.asyncio
async def test_two_dead_pairings_lock_new_windows_until_the_owner_acknowledges(mgr, monkeypatch):
    _fake_totp(monkeypatch)
    await mgr.set_enabled(True)
    async with make_app(mgr, via_link=True) as c:
        await _dead_pairing(c, mgr)
        assert mgr.pairing.pairing_view()["state"] == "failed" and not mgr.pairing.locked()
        await _dead_pairing(c, mgr)
        assert mgr.pairing.locked() and mgr.pairing.pairing_view()["locked"] is True
    async with make_app(mgr) as owner:
        refused = await owner.post("/api/v1/phone-link/pairing-window")
        assert refused.status_code == 409 and refused.json()["code"] == "pairing_locked"
        assert not mgr.pairing.window_open()
        assert (await owner.post("/api/v1/phone-link/pairing-window/acknowledge")).json() == {"acknowledged": True}
        assert (await owner.post("/api/v1/phone-link/pairing-window")).status_code == 200


@pytest.mark.asyncio
async def test_totp_failure_text_never_reaches_a_link_client(mgr, monkeypatch):
    from src.api import auth_routes
    def boom():
        raise RuntimeError("/secret/path")

    monkeypatch.setattr(auth_routes, "settings", type("S", (), {"load_auth_config": staticmethod(boom)}))
    await mgr.set_enabled(True)
    w = mgr.pairing.open_window()
    async with make_app(mgr, via_link=True) as c:
        pending = (await c.post("/pair/claim", json={"secret": w.secret})).headers["set-cookie"].split(";")[0]
        r = await c.post("/pair/verify", json={"code": "000000"}, headers={"cookie": pending})
    assert r.status_code == 500 and "secret" not in r.text and r.json()["detail"] == "authentication error"


@pytest.mark.asyncio
async def test_the_totp_rate_limit_applies_on_pair_verify(mgr):
    await mgr.set_enabled(True)
    async with make_app(mgr, via_link=True) as c:
        codes = [(await c.post("/pair/verify", json={"code": "000000"})).status_code for _ in range(6)]
    assert codes[:5] == [403] * 5 and codes[5] == 429


@pytest.mark.asyncio
async def test_a_right_code_with_no_pending_left_revokes_the_token_it_issued(mgr, monkeypatch):
    orphans = []

    async def redeem(request, code):
        mgr.pairing.close_window()
        return _Tokens()

    async def revoke_orphan(request, refresh_token):
        orphans.append(refresh_token)

    monkeypatch.setattr(routes, "redeem_totp_code", redeem)
    monkeypatch.setattr(routes, "_revoke_orphan", revoke_orphan)
    await mgr.set_enabled(True)
    w = mgr.pairing.open_window()
    async with make_app(mgr, via_link=True) as c:
        pending = (await c.post("/pair/claim", json={"secret": w.secret})).headers["set-cookie"].split(";")[0]
        r = await c.post("/pair/verify", json={"code": "123456"}, headers={"cookie": pending})
    assert r.status_code == 403 and r.json()["detail"] == "no_pending" and orphans == ["refresh.jwt"]


@pytest.mark.asyncio
async def test_revoke_orphan_revokes_the_jti_in_the_store(monkeypatch):
    from types import SimpleNamespace
    revoked = []

    class _Store:
        async def revoke(self, jti):
            revoked.append(jti)

    monkeypatch.setattr(routes, "decode_refresh_token", lambda token: {"jti": "j1"})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(refresh_store=_Store())))
    await routes._revoke_orphan(request, "refresh.jwt")
    assert revoked == ["j1"]

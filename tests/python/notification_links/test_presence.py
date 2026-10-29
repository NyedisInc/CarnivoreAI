
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from src.api import notification_link_routes, notification_presence_routes
from src.api.auth import require_auth
from src.core.notifications import links, presence as presence_mod
from src.core.notifications.presence import MAX_LEASES, PresenceLeases

CID = "tab-12345678"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_lease_expires_at_60s():
    c = Clock()
    p = PresenceLeases(clock=c)
    assert not p.is_screen_active()
    assert p.beacon(CID, True)
    c.t = 59.9
    assert p.is_screen_active()
    c.t = 60.0
    assert not p.is_screen_active()


def test_beacon_renews_and_inactive_drops_at_once():
    c = Clock()
    p = PresenceLeases(clock=c)
    p.beacon(CID, True)
    c.t = 50
    p.beacon(CID, True)
    c.t = 100
    assert p.is_screen_active()
    p.beacon(CID, False)
    assert not p.is_screen_active()


def test_cap_evicts_oldest():
    c = Clock()
    p = PresenceLeases(clock=c)
    for i in range(MAX_LEASES + 1):
        c.t = i * 0.01
        p.beacon(f"client-{i:04d}", True)
    assert len(p._leases) == MAX_LEASES
    assert "client-0000" not in p._leases and f"client-{MAX_LEASES:04d}" in p._leases


@pytest.mark.parametrize("bad", ["", "short", "has space 1234", "x" * 65, "a/b/c/d/e/f"])
def test_bad_client_id_refused(bad):
    p = PresenceLeases(clock=Clock())
    assert p.beacon(bad, True) is False
    assert not p.is_screen_active()


def make_app(authed: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(notification_link_routes.router, prefix="/api/v1")
    app.include_router(notification_presence_routes.router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: {"sub": "owner"}
    return app


async def call(app, method, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.request(method, path, **kw)


@pytest.mark.asyncio
async def test_routes_authenticated(monkeypatch):
    fresh = PresenceLeases()
    monkeypatch.setattr(presence_mod, "presence", fresh)
    monkeypatch.setattr(notification_presence_routes, "presence", fresh)
    monkeypatch.setattr(links, "resolver", links.LinkResolver(
        bound_host=lambda: "127.0.0.1", machine_names=lambda: frozenset(), ipv4_addresses=lambda: [], port=lambda: 1))
    app = make_app(True)
    r = await call(app, "GET", "/api/v1/notifications/link")
    assert r.status_code == 200
    assert r.json() == {"kind": "none", "base": "", "reason": "bound_loopback_only"}
    r = await call(app, "POST", "/api/v1/notifications/presence", json={"client_id": CID, "active": True})
    assert r.status_code == 200 and fresh.is_screen_active()
    r = await call(app, "POST", "/api/v1/notifications/presence", json={"client_id": "bad", "active": True})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_routes_refuse_unauthenticated():
    app = make_app(False)
    assert (await call(app, "GET", "/api/v1/notifications/link")).status_code in (401, 403)
    r = await call(app, "POST", "/api/v1/notifications/presence", json={"client_id": CID, "active": True})
    assert r.status_code in (401, 403)

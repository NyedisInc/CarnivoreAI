
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import app_update_peer_routes, peer_auth
from src.api.auth import require_auth
from src.core.app_update import store
from src.core.federation import peer_app_update, peer_links
from src.core.federation.peer_client import PeerUnreachable
from src.core.pack.machines import config_state
from src.core.pack.machines.restrictions import Restrictions

STUDIO = "peer-4d3f86db2ae6cf5f23e5"
STATUS = {"attached": True, "state": "available", "current_version": "1.17.0", "latest_version": "1.17.1", "percent": None,
          "detail": None, "checked_at": 1.0, "auto_update": False, "command_seq": 4, "command": "check"}


class FakeClient:
    def __init__(self, answers):
        self.calls, self.answers = [], answers

    async def request(self, method, path, *, json=None, **_kw):
        self.calls.append((method, path, json))
        answer = self.answers[(method, path)]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(status_code=answer[0], json=lambda: answer[1])


class FakeLinks:
    def __init__(self, client):
        self._client = client

    def client(self, _iid):
        return self._client


@pytest.fixture
def world(monkeypatch, tmp_path):
    peer = SimpleNamespace(key=STUDIO, peer_install_id="iid-studio", label="studio")
    monkeypatch.setattr(peer_app_update.peer_hosts, "list_peers", lambda conn: [peer])
    monkeypatch.setattr(peer_auth, "open_db", lambda: SimpleNamespace(close=lambda: None))
    client = FakeClient({("GET", "/federation/app-update"): (200, STATUS),
                         ("POST", "/federation/app-update/check"): (200, STATUS),
                         ("POST", "/federation/app-update/install"): (200, STATUS),
                         ("PUT", "/federation/app-update/auto-update"): (200, {**STATUS, "auto_update": True})})
    monkeypatch.setattr(peer_links, "LINKS", FakeLinks(client))
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(app_update_peer_routes.served, prefix="/api/v1")
    app.include_router(app_update_peer_routes.asked, prefix="/api/v1")
    c = TestClient(app)
    c.peer, c.app_ = client, app
    return c


def test_allowed_calls_reach_the_peer_and_show_only_the_status_fields(world):
    body = world.get(f"/api/v1/app-update/computer/{STUDIO}").json()
    assert body["status"] == "ok" and body["update"]["latest_version"] == "1.17.1"
    assert "command_seq" not in body["update"]
    assert world.post(f"/api/v1/app-update/computer/{STUDIO}/check").json()["status"] == "ok"
    assert world.post(f"/api/v1/app-update/computer/{STUDIO}/install").json()["status"] == "ok"
    assert world.put(f"/api/v1/app-update/computer/{STUDIO}/auto-update", json={"enabled": True}).json()["update"]["auto_update"] is True
    assert [c[:2] for c in world.peer.calls] == [("GET", "/federation/app-update"), ("POST", "/federation/app-update/check"),
                                                 ("POST", "/federation/app-update/install"), ("PUT", "/federation/app-update/auto-update")]
    assert world.peer.calls[-1][2] == {"enabled": True}


def test_a_feed_url_or_any_other_field_is_refused_before_the_peer(world):
    for body in ({"enabled": True, "feed_url": "https://evil.example"}, {"feed_url": "https://evil.example"}, {"enabled": "yes"}):
        assert world.put(f"/api/v1/app-update/computer/{STUDIO}/auto-update", json=body).status_code == 422
    assert world.peer.calls == []


def test_a_request_that_arrived_from_a_peer_is_not_forwarded(world):
    world.app_.dependency_overrides[app_update_peer_routes.require_auth] = lambda: None

    @world.app_.middleware("http")
    async def as_peer(request, call_next):
        request.state.peer_grant = object()
        return await call_next(request)

    assert world.get(f"/api/v1/app-update/computer/{STUDIO}").json() == {"status": "unavailable", "reason": "not_local"}
    assert world.post(f"/api/v1/app-update/computer/{STUDIO}/install").json()["reason"] == "not_local"
    assert world.peer.calls == []


def test_an_old_computer_reads_as_unsupported_not_an_error(world):
    world.peer.answers[("GET", "/federation/app-update")] = (404, {"detail": "Not Found"})
    world.peer.answers[("POST", "/federation/app-update/install")] = (405, {"detail": "Method Not Allowed"})
    assert world.get(f"/api/v1/app-update/computer/{STUDIO}").json() == {"status": "unsupported"}
    assert world.post(f"/api/v1/app-update/computer/{STUDIO}/install").json() == {"status": "unsupported"}


def test_refusals_and_a_dead_link_are_named_not_raised(world):
    world.peer.answers[("POST", "/federation/app-update/install")] = (403, {"detail": {"code": "pack_restricted"}})
    assert world.post(f"/api/v1/app-update/computer/{STUDIO}/install").json() == {"status": "refused", "reason": "pack_restricted"}
    world.peer.answers[("POST", "/federation/app-update/check")] = (409, {"detail": "no desktop app is attached to this server"})
    assert world.post(f"/api/v1/app-update/computer/{STUDIO}/check").json()["reason"] == "http_409"
    world.peer.answers[("GET", "/federation/app-update")] = PeerUnreachable("down")
    assert world.get(f"/api/v1/app-update/computer/{STUDIO}").json() == {"status": "unavailable", "reason": "unreachable"}
    assert world.get("/api/v1/app-update/computer/peer-nobody").json()["reason"] == "not_paired"


def _serve(monkeypatch, peer_kind, may_update):
    store.reset_for_tests()
    monkeypatch.setattr(config_state.default(), "restrictions", lambda: Restrictions(may_update_carnivore=may_update), raising=False)
    app = FastAPI()
    grant = SimpleNamespace(peer_install_id="iid-x")
    app.dependency_overrides[app_update_peer_routes._peer] = lambda: peer_auth.Principal(peer_kind, grant if peer_kind == "peer" else None)
    app.include_router(app_update_peer_routes.served, prefix="/api/v1")
    return TestClient(app)


def test_a_peer_write_needs_this_computers_own_rule_but_a_read_does_not(monkeypatch):
    c = _serve(monkeypatch, "peer", may_update=False)
    assert c.get("/api/v1/federation/app-update").status_code == 200
    for method, path, body in (("put", "/auto-update", {"enabled": True}), ("post", "/check", None), ("post", "/install", None)):
        r = getattr(c, method)("/api/v1/federation/app-update" + path, **({"json": body} if body else {}))
        assert r.status_code == 403 and r.json()["detail"]["code"] == "pack_restricted"


def test_a_peer_write_is_accepted_when_the_rule_allows_it(monkeypatch, tmp_path):
    from src.config import settings

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"updates": {"feed_url": "https://u.example/app"}}))
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    c = _serve(monkeypatch, "peer", may_update=True)
    assert c.put("/api/v1/federation/app-update/auto-update", json={"enabled": True}).json()["auto_update"] is True
    assert json.loads(cfg.read_text())["updates"]["feed_url"] == "https://u.example/app"
    store.reset_for_tests()


def test_the_served_routes_hold_no_state_or_feed_route():
    paths = {(m, r.path) for r in app_update_peer_routes.served.routes for m in r.methods}
    assert paths == {("GET", "/federation/app-update"), ("PUT", "/federation/app-update/auto-update"),
                     ("POST", "/federation/app-update/check"), ("POST", "/federation/app-update/install")}

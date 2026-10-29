
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from tests.lifecycle_helpers import add_row  # noqa: F401,E402

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import notification_settings_routes as set_routes
from src.api import notification_sync_routes as sync_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import fed_key, grants, pairing, peer_links
from src.core.notifications.sync import status as st
from src.core.notifications.sync.peers import LinkGateway, PeerInfo


@pytest.fixture()
def conn(tmp_path: Path):
    ensure_db_migrated(tmp_path)
    with closing(connect(db_path_for(tmp_path), create=False)) as c:
        yield c


def _key() -> str:
    return fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([7]) * 32))


def test_the_protocol_minor_is_one_and_the_scope_is_known():
    assert pairing.PROTOCOL_MINOR >= 1
    assert grants.SCOPE_SETTINGS == "settings" and "settings" in grants.KNOWN_SCOPES


def test_set_scopes_changes_a_live_grant_only(conn):
    g = grants.create_grant(conn, peer_install_id="iid-hosta", public_key=_key(), label="hosta")
    assert g.scopes == ("sessions",)
    assert grants.set_scopes(conn, g.grant_id, ("sessions", "settings")) is True
    assert grants.get_live(conn, g.grant_id).allows("settings")
    assert grants.set_scopes(conn, g.grant_id, ("settings", "sessions")) is False
    with pytest.raises(grants.GrantError):
        grants.set_scopes(conn, g.grant_id, ("sessions", "root"))
    with pytest.raises(grants.GrantError):
        grants.set_scopes(conn, g.grant_id, ())
    grants.revoke(conn, g.grant_id)
    assert grants.set_scopes(conn, g.grant_id, ("sessions",)) is False


def test_the_link_gateway_toggles_the_settings_scope_and_keeps_the_rest(conn, tmp_path):
    g = grants.create_grant(conn, peer_install_id="iid-hosta", public_key=_key(), label="hosta")
    gateway = LinkGateway(lambda: connect(db_path_for(tmp_path), create=False), lambda: None)
    asyncio.run(gateway.set_scope("iid-hosta", True))
    assert set(grants.get_live(conn, g.grant_id).scopes) == {"sessions", "settings"}
    asyncio.run(gateway.set_scope("iid-hosta", False))
    assert grants.get_live(conn, g.grant_id).scopes == ("sessions",)
    asyncio.run(gateway.set_scope("iid-nobody", True))


def test_the_connect_listener_fires_once_per_connection(monkeypatch):
    links = peer_links.PeerLinks(open_db=lambda: None, listener_path="x")
    monkeypatch.setattr(links, "_write_state", lambda *a: None)
    seen = []
    links.add_connect_listener(seen.append)

    async def go():
        up = links._persist_state("iid-1")
        up("connecting", None)
        up("connected", 1)
        up("connected", 1)
        up("disconnected", 1)
        up("connected", 1)

    asyncio.run(go())
    assert seen == ["iid-1", "iid-1"]


class _Gateway:
    def __init__(self, peers):
        self.peers = peers

    async def roster(self):
        return self.peers


def _client(service, peers):
    from src.core.notifications.sync.manager import SyncManager

    app = FastAPI()
    app.include_router(set_routes.router, prefix="/api/v1")
    app.include_router(sync_routes.router, prefix="/api/v1")
    app.state.notification_service = service
    manager = SyncManager(service.docs, service.secrets, _Gateway(peers))
    app.state.notification_sync = manager
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app), manager


def test_the_owner_routes_show_switch_and_wake_the_sync(cluster, make):
    a = make("A")
    peers = [PeerInfo("peer-new", "hosta", "iid-new", True, 1), PeerInfo("peer-old", "attic", "iid-old", True, 0),
             PeerInfo("peer-down", "away", "iid-down", False, 0)]
    client, manager = _client(a.service, peers)
    manager.status.record("iid-new", st.R_OK, 1234.0)
    body = client.get("/api/v1/notifications/sync").json()
    assert body["available"] is True
    by_key = {p["key"]: p for p in body["peers"]}
    assert by_key["peer-new"] == {"key": "peer-new", "label": "hosta", "enabled": True, "protocol": "ok",
                                  "connected": True, "last_exchange_at": 1234.0, "last_result": "ok"}
    assert by_key["peer-old"]["protocol"] == "older" and by_key["peer-down"]["protocol"] == "unknown"
    off = client.put("/api/v1/notifications/sync/peers/peer-new", json={"enabled": False})
    assert off.status_code == 200 and {p["key"]: p["enabled"] for p in off.json()["peers"]}["peer-new"] is False
    assert st.is_enabled(a.doc(), "iid-new") is False and st.is_enabled(a.doc(), "iid-old") is True
    assert client.put("/api/v1/notifications/sync/peers/nobody", json={"enabled": True}).status_code == 404
    assert client.post("/api/v1/notifications/sync/now").json() == {"started": True}
    assert client.get("/api/v1/notifications/settings").json()["sync"] == client.get("/api/v1/notifications/sync").json()
    assert "sync_off" not in str(a.doc()["global"])


def test_the_owner_routes_need_login_and_a_running_sync(cluster, make):
    a = make("A")
    client, _ = _client(a.service, [])
    client.app.dependency_overrides.clear()
    assert client.get("/api/v1/notifications/sync").status_code in (401, 403)
    client.app.dependency_overrides[require_auth] = lambda: None
    client.app.state.notification_sync = None
    assert client.get("/api/v1/notifications/sync").json() == {"available": False, "peers": []}
    assert client.post("/api/v1/notifications/sync/now").status_code == 503
    assert client.get("/api/v1/notifications/settings").json()["sync"] == {"available": False, "peers": []}


def test_a_local_change_wakes_the_loop_and_a_local_only_change_does_not(cluster, make):
    from src.core.notifications.settings_doc import ticks

    a = make("A")
    make("B")
    cluster.link("A", "B")

    async def go():
        a.manager.attach()
        a.manager._wake.clear()
        await asyncio.to_thread(ticks.put_default, a.service.docs, "session.finished", False)
        await asyncio.sleep(0.05)
        woke_global = a.manager._wake.is_set()
        a.manager._wake.clear()
        await asyncio.to_thread(ticks.set_paused, a.service.docs, True)
        await asyncio.sleep(0.05)
        return woke_global, a.manager._wake.is_set()

    assert asyncio.run(go()) == (True, False)


def test_the_loop_runs_a_pass_after_a_trigger_and_retries_a_refused_pass(cluster, make, monkeypatch):
    from src.core.notifications.sync import manager as manager_mod

    a, b = make("A"), make("B")
    cluster.link("A", "B")
    monkeypatch.setattr(manager_mod, "DEBOUNCE_SECONDS", 0.0)
    monkeypatch.setattr(manager_mod, "RETRY_SECONDS", 0.05)

    async def go():
        task = asyncio.create_task(a.manager.run())
        await asyncio.sleep(0.05)
        a.manager.request_sync()
        for _ in range(100):
            await asyncio.sleep(0.02)
            if cluster.sent and a.manager.status.get("B") and a.manager.status.get("B").result == "refused":
                break
        first = len(cluster.sent)
        b.manager.gateway.cluster.grants.add(("A", "B"))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if a.manager.status.get("B").result != "refused":
                break
        task.cancel()
        return first, a.manager.status.get("B").result

    first, result = asyncio.run(go())
    assert first >= 1 and result in ("ok", "no_change")

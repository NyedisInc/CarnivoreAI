
from __future__ import annotations

import asyncio
import json

import pytest
from structlog.testing import capture_logs

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import federation_notify_sync_routes as peer_routes  # noqa: E402
from src.api.peer_auth import OWNER, Principal  # noqa: E402
from src.core.federation.grants import Grant  # noqa: E402
from src.core.notifications.sync import secrets_sync, seen  # noqa: E402

from .test_converge import create, link_all, rounds  # noqa: E402

SENTINEL = "SYNCSENTINEL-4c1d"
URL = f"https://hooks.slack.com/services/T0/B0/{SENTINEL}"


def test_a_secret_lands_only_in_the_keychain(cluster, make, caplog):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    dest = create(a, url=URL)
    with capture_logs() as logs:
        rounds(a, b)
    assert any(SENTINEL in v for v in b.keychain.items.values()) is False
    got = asyncio.run(b.service.secrets.get(dest))
    assert got == {"url": URL}
    assert seen.seen_rev(b.doc(), dest) == 1
    for blob in (b.path.read_text(), a.path.read_text(), json.dumps(logs, default=str), caplog.text,
                 json.dumps(cluster.answers), json.dumps([x[3] for x in cluster.sent if x[2].endswith("exchange")])):
        assert SENTINEL not in blob
    assert not list(b.path.parent.glob("B.json.bak*")) or all(SENTINEL not in p.read_text() for p in b.path.parent.glob("B.json.bak*"))
    assert SENTINEL in json.dumps(cluster.secret_answers)


def test_a_secret_change_reaches_the_peer_by_revision(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    dest = create(a, url=URL)
    rounds(a, b)
    asyncio.run(a.service.destinations.update(dest, secret_patch={"url": URL + "2"}))
    assert a.doc()["global"][f"dest/{dest}"]["val"]["secret_rev"] == 2
    rounds(a, b)
    assert asyncio.run(b.service.secrets.get(dest)) == {"url": URL + "2"}
    assert seen.seen_rev(b.doc(), dest) == 2


def test_a_revision_is_not_marked_seen_when_the_keychain_write_fails(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    dest = create(a, url=URL)
    b.keychain.fail_writes = True
    rounds(a, b)
    assert seen.seen_rev(b.doc(), dest) == 0 and b.keychain.items == {}
    assert seen.stale_destinations(b.doc()) == [dest]
    b.keychain.fail_writes = False
    rounds(a, b, n=1)
    assert seen.seen_rev(b.doc(), dest) == 1 and b.keychain.items


def test_a_peer_that_is_behind_leaves_the_destination_stale(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    dest = create(a, url=URL)
    rounds(a, b, n=1)
    asyncio.run(a.service.destinations.update(dest, secret_patch={"url": URL + "3"}))

    async def behind(ids):
        return {"secrets": {dest: {"rev": 1, "fields": {"url": URL}}}}

    rounds(b, a, n=1)
    b.service.docs.update(lambda d, me: seen.mark_seen(d, dest, 1))
    result = asyncio.run(secrets_sync.pull_stale(b.service.docs, b.service.secrets, behind, "A"))
    assert result.stored == [] and result.still_stale == [dest]
    assert seen.seen_rev(b.doc(), dest) == 1


def make_app(service) -> TestClient:
    app = FastAPI()
    app.include_router(peer_routes.router, prefix="/api/v1")
    app.state.notification_service = service
    grant = Grant("g1", "peer-install", "pk", "fid", "studio", ("sessions", "settings"), None, "now", None, None)
    app.dependency_overrides[peer_routes._require_settings] = lambda: Principal("peer", grant)
    app.state.test_grant = grant
    return TestClient(app)


def test_the_secrets_route_refuses_local_scope_sends_no_store_and_limits_to_30_a_minute(cluster, make, monkeypatch):
    a = make("A")
    global_id = create(a, url=URL)
    local_id = create(a, name="mine", scope="local", url="https://hooks.slack.com/services/T9/B9/LOCALSENTINEL")
    monkeypatch.setattr(peer_routes, "_secret_limiter", secrets_sync.RateLimiter())
    client = make_app(a.service)
    ok = client.post("/api/v1/federation/notify-sync/secrets", json={"dest_ids": [global_id, local_id]})
    assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"
    body = ok.json()
    assert body["secrets"][global_id] == {"rev": 1, "fields": {"url": URL}}
    assert body["refused"] == [local_id] and local_id not in body["secrets"]
    assert "LOCALSENTINEL" not in ok.text
    for _ in range(29):
        assert client.post("/api/v1/federation/notify-sync/secrets", json={"dest_ids": []}).status_code == 200
    limited = client.post("/api/v1/federation/notify-sync/secrets", json={"dest_ids": [global_id]})
    assert limited.status_code == 429 and limited.headers["cache-control"] == "no-store" and URL not in limited.text


def test_the_peer_routes_refuse_the_owner_login(cluster, make):
    a = make("A")
    client = make_app(a.service)
    client.app.dependency_overrides[peer_routes._require_settings] = lambda: OWNER
    assert client.post("/api/v1/federation/notify-sync/secrets", json={"dest_ids": []}).status_code == 403
    exchange = {"v": 1, "digest": "x", "buckets": 1, "bucket": 0, "entries": {}}
    assert client.post("/api/v1/federation/notify-sync/exchange", json=exchange).status_code == 403


def test_the_exchange_route_answers_no_store_and_rejects_a_bad_bucket(cluster, make):
    a = make("A")
    client = make_app(a.service)
    good = client.post("/api/v1/federation/notify-sync/exchange",
                       json={"v": 1, "digest": "x", "buckets": 1, "bucket": 0, "entries": {}})
    assert good.status_code == 200 and good.headers["cache-control"] == "no-store"
    bad = client.post("/api/v1/federation/notify-sync/exchange",
                      json={"v": 1, "digest": "x", "buckets": 2, "bucket": 5, "entries": {}})
    assert bad.status_code == 422
    wrong = client.post("/api/v1/federation/notify-sync/exchange",
                        json={"v": 9, "digest": "x", "buckets": 1, "bucket": 0, "entries": {}})
    assert wrong.status_code == 422


def test_a_malformed_incoming_entry_is_dropped_not_stored(cluster, make):
    a = make("A")
    client = make_app(a.service)
    evil = {
        "dest/d_000000000001": {"val": {"kind": "webhook", "name": "x", "enabled": True,
                                        "config": {"url": "http://127.0.0.1/hook"}}, "ver": [5, "n_x"]},
        "tick/screen/session.finished": {"val": "yes", "ver": [5, "n_x"]},
        "local/paused": {"val": True, "ver": [5, "n_x"]},
        "dest/webpush:7": {"val": {"kind": "webpush", "name": "p", "enabled": True}, "ver": [5, "n_x"]},
        "default/session.died": {"val": False, "ver": [2, "n_x"]},
    }
    r = client.post("/api/v1/federation/notify-sync/exchange",
                    json={"v": 1, "digest": "x", "buckets": 1, "bucket": 0, "entries": evil})
    assert r.status_code == 200
    g = a.doc()["global"]
    assert set(g) & set(evil) == {"default/session.died"}
    assert "paused" not in json.dumps(a.doc()["local"])

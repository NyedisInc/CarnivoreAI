
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
import structlog
from structlog.testing import capture_logs

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import notification_destinations_routes as dest_routes  # noqa: E402
from src.api import notification_settings_routes as set_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.notifications import doc_model, kind_specs, types  # noqa: E402
from src.core.notifications.destinations import extras as extras_mod  # noqa: E402
from src.core.notifications.settings_doc import ticks, view  # noqa: E402

from .conftest import slack_body  # noqa: E402

SENTINEL = "SENTINEL-xyzzy-9f3a"
SENT_URL = f"https://hooks.slack.com/services/T0/B0/{SENTINEL}"
BASE = "/api/v1/notifications"


def make_client(service, authed: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(set_routes.router, prefix="/api/v1")
    app.include_router(dest_routes.router, prefix="/api/v1")
    app.state.notification_service = service
    if authed:
        app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def create(client: TestClient, **over) -> dict:
    r = client.post(f"{BASE}/destinations", json={**slack_body(), **over})
    assert r.status_code == 201, r.text
    return r.json()


def test_sentinel_never_in_config_bak_responses_or_logs(service, config_path, caplog):
    client = make_client(service)
    caplog.set_level(logging.DEBUG)
    responses = []
    with capture_logs() as logs:
        made = create(client, secrets={"url": SENT_URL})
        responses.append(json.dumps(made))
        dest_id = made["destination"]["id"]
        responses.append(client.get(f"{BASE}/settings").text)
        responses.append(client.get(f"{BASE}/destinations").text)
        patched = client.patch(f"{BASE}/destinations/{dest_id}", json={"name": "renamed", "secrets": {"url": SENT_URL + "2"}})
        responses.append(patched.text)
        client.put(f"{BASE}/destinations/{dest_id}/extras", json={"details": True})
    blob = "\n".join(responses + [json.dumps(logs, default=str), caplog.text])
    blob += config_path.read_text() + config_path.with_suffix(".json.bak").read_text()
    assert SENTINEL not in blob
    assert made["destination"]["secrets"] == {"url": {"set": True}}
    assert any(k == "hooks.slack.com" or "slack" in k for k in [made["destination"]["kind"]])
    assert logs, "no log lines captured, so the log check proved nothing"


def test_create_seeds_ticks_with_kind_exclusions(service):
    client = make_client(service)
    slack = create(client)["destination"]["id"]
    pd = create(client, kind="pagerduty", name="pd", secrets={"routing_key": "rk"})["destination"]["id"]
    ticks_all = client.get(f"{BASE}/settings").json()["ticks"]
    assert ticks_all[slack]["session.finished"]["value"] is True
    assert ticks_all[pd]["session.finished"]["value"] is False
    assert ticks_all[pd]["provider.needs_login"]["value"] is True
    for col in (slack, pd):
        assert ticks_all[col]["alert.notifications"] == {"value": False, "source": "locked", "locked": True}
        assert ticks_all[col]["agent.message"]["value"] is False


def test_locked_cells_refused_and_needs_you_screen_cell_can_be_unticked(service):
    client = make_client(service)
    dest = create(client)["destination"]["id"]
    for type_id in ("session.permission", "approval.agent_action"):
        assert client.get(f"{BASE}/settings").json()["screen"][type_id] == {"value": True, "source": "default", "locked": False}
        r = client.put(f"{BASE}/ticks", json={"column": "screen", "type_id": type_id, "value": False})
        assert r.status_code == 200, r.text
        assert client.get(f"{BASE}/settings").json()["screen"][type_id]["value"] is False
    r = client.put(f"{BASE}/ticks", json={"column": dest, "type_id": "alert.notifications", "value": True})
    assert r.status_code == 409
    assert client.put(f"{BASE}/ticks", json={"column": "d_ffffffffffff", "type_id": "session.finished", "value": True}).status_code == 404
    assert client.put(f"{BASE}/ticks", json={"column": dest, "type_id": "nope", "value": True}).status_code == 422


def test_pin_then_reset(service):
    client = make_client(service)
    dest = create(client)["destination"]["id"]
    put = lambda **b: client.put(f"{BASE}/ticks", json={"column": dest, "type_id": "session.finished", **b})  # noqa: E731
    cell = put(value=False, scope="local").json()["cell"]
    assert cell == {"value": False, "source": "local", "locked": False}
    assert put(value=False).json()["cell"]["source"] == "local"
    doc = service.docs.snapshot()
    assert doc["global"][doc_model.tick_path(dest, "session.finished")]["val"] is True
    r = client.delete(f"{BASE}/overrides", params={"path": doc_model.tick_path(dest, "session.finished")})
    assert r.json()["reset"] is True
    assert client.get(f"{BASE}/settings").json()["ticks"][dest]["session.finished"] == {"value": True, "source": "global", "locked": False}
    assert client.delete(f"{BASE}/overrides", params={"path": doc_model.tick_path(dest, "session.finished")}).json()["reset"] is False
    assert client.delete(f"{BASE}/overrides", params={"path": "bogus"}).status_code == 422


def test_local_scope_destination_not_global_and_not_resettable(service):
    client = make_client(service)
    dest = create(client, scope="local")["destination"]["id"]
    doc = service.docs.snapshot()
    assert not any(dest in p for p in doc["global"])
    assert client.get(f"{BASE}/destinations").json()["destinations"][0]["scope"] == "local"
    r = client.delete(f"{BASE}/overrides", params={"path": doc_model.dest_path(dest)})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "not_resettable"


def test_delete_tombstones_everything_and_removes_keychain_item(service, keychain, config_path):
    client = make_client(service)
    dest = create(client)["destination"]["id"]
    client.put(f"{BASE}/destinations/{dest}/extras", json={"away": True})
    assert len(keychain.items) == 1
    assert client.delete(f"{BASE}/destinations/{dest}").json() == {"deleted": True}
    assert keychain.items == {}
    doc = service.docs.snapshot()
    owned = [p for p in doc["global"] if dest in p]
    assert owned and all("tomb" in doc["global"][p] for p in owned)
    assert client.get(f"{BASE}/destinations").json()["destinations"] == []
    assert client.delete(f"{BASE}/destinations/{dest}").status_code == 404
    assert dest not in view.dest_ids(doc)


def test_failed_keychain_create_saves_nothing(service, keychain):
    client = make_client(service)
    keychain.fail_writes = True
    r = client.post(f"{BASE}/destinations", json=slack_body())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "destination_keychain_unavailable"
    assert client.get(f"{BASE}/destinations").json()["destinations"] == []
    assert keychain.items == {}


def test_oversize_secret_bundle_is_a_422_and_writes_nothing(service, keychain, monkeypatch):
    from src.core.notifications.destinations import secrets as secrets_mod

    monkeypatch.setattr(secrets_mod, "MAX_ENCODED_BYTES", 8)
    client = make_client(service)
    r = client.post(f"{BASE}/destinations", json=slack_body())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "destination_secret_too_large"
    assert client.get(f"{BASE}/destinations").json()["destinations"] == []
    assert keychain.items == {}


def test_webhook_signing_secret_generated_once(service, keychain):
    client = make_client(service)
    body = {"kind": "webhook", "name": "hook", "secrets": {"url": "https://example.com/in"}}
    made = client.post(f"{BASE}/destinations", json=body).json()
    secret = made["signing_secret"]
    assert len(secret) >= 32
    assert made["destination"]["secrets"]["signing_secret"] == {"set": True}
    assert secret not in client.get(f"{BASE}/destinations").text + client.get(f"{BASE}/settings").text
    mine = {"kind": "webhook", "name": "own", "secrets": {"url": "https://example.com/in", "signing_secret": "mine-1"}}
    assert "signing_secret" not in client.post(f"{BASE}/destinations", json=mine).json()


def test_patch_blank_secret_untouched_and_validation(service, keychain):
    client = make_client(service)
    dest = create(client)["destination"]["id"]
    before = dict(keychain.items)
    r = client.patch(f"{BASE}/destinations/{dest}", json={"secrets": {"url": "  "}, "name": "x"})
    assert r.status_code == 200 and keychain.items == before
    assert client.patch(f"{BASE}/destinations/{dest}", json={"secrets": {"url": "https://evil.example/x"}}).status_code == 422
    assert client.post(f"{BASE}/destinations", json=slack_body("http://hooks.slack.com/x")).status_code == 422
    assert client.post(f"{BASE}/destinations", json={"kind": "webpush", "name": "n"}).status_code == 422
    bad = client.post(f"{BASE}/destinations", json={"kind": "slack", "name": "n", "secrets": {}}).json()
    assert bad["detail"]["fields"] == {"url": "required"}
    local = client.patch(f"{BASE}/destinations/{dest}", json={"enabled": False, "scope": "local"}).json()["destination"]
    assert local["enabled"] is False and local["pinned"] is True
    assert client.delete(f"{BASE}/overrides", params={"path": doc_model.dest_path(dest)}).json()["reset"] is True
    assert client.get(f"{BASE}/destinations").json()["destinations"][0]["enabled"] is True


def test_extras_roundtrip_and_details_refused_for_sms(service):
    client = make_client(service)
    dest = create(client)["destination"]["id"]
    r = client.put(f"{BASE}/destinations/{dest}/extras", json={
        "away": True, "quiet": {"start": "22:00", "end": "07:00"}, "reminder_minutes": 10, "projects": ["b", "a"], "details": True})
    assert r.json()["destination"]["extras"] == {
        "away": True, "quiet": {"start": "22:00", "end": "07:00"}, "reminder_minutes": 10, "projects": ["a", "b"], "details": True}
    assert client.put(f"{BASE}/destinations/{dest}/extras", json={"quiet": None}).json()["destination"]["extras"]["quiet"] is None
    assert client.put(f"{BASE}/destinations/{dest}/extras", json={"quiet": {"start": "25:00", "end": "07:00"}}).status_code == 422
    assert client.put(f"{BASE}/destinations/{dest}/extras", json={"reminder_minutes": 0}).status_code == 422
    twilio = client.post(f"{BASE}/destinations", json={"kind": "twilio", "name": "sms", "secrets": {
        "sid": "AC1", "token": "t", "from_number": "+15550001111", "numbers": ["+15550002222"]}}).json()["destination"]["id"]
    r = client.put(f"{BASE}/destinations/{twilio}/extras", json={"details": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "destination_details_not_allowed"
    assert client.put(f"{BASE}/destinations/d_ffffffffffff/extras", json={"away": True}).status_code == 404


def test_every_write_path_notifies_the_topic(service, notified):
    client = make_client(service)
    steps = []
    dest = create(client)["destination"]["id"]
    steps.append("create")
    calls = [
        lambda: client.patch(f"{BASE}/destinations/{dest}", json={"name": "n2"}),
        lambda: client.put(f"{BASE}/destinations/{dest}/extras", json={"away": True}),
        lambda: client.put(f"{BASE}/ticks", json={"column": "screen", "type_id": "session.finished", "value": False}),
        lambda: client.put(f"{BASE}/defaults", json={"type_id": "session.finished", "value": False}),
        lambda: client.put(f"{BASE}/settings", json={"paused": True}),
        lambda: client.put(f"{BASE}/ticks", json={"column": "screen", "type_id": "session.finished", "value": True, "scope": "local"}),
        lambda: client.delete(f"{BASE}/overrides", params={"path": "tick/screen/session.finished"}),
        lambda: asyncio.run(service.routing.disable_locally(dest, "t")),
        lambda: asyncio.run(service.destinations.seed_destination_ticks("webpush:abc", "webpush")),
        lambda: client.delete(f"{BASE}/destinations/{dest}"),
    ]
    assert notified.count("notification_settings") >= 1
    for call in calls:
        before = len(notified)
        call()
        assert len(notified) == before + 1, "a write path did not announce notification_settings"
    assert set(notified) == {"notification_settings"}


def test_topic_registered():
    from src.core.resource_push import topics

    assert "notification_settings" in topics.RESOURCE_TOPICS


def test_every_route_refuses_unauthenticated(service):
    client = make_client(service, authed=False)
    d = "d_0123456789ab"
    calls = [
        client.get(f"{BASE}/settings"), client.put(f"{BASE}/settings", json={"paused": True}),
        client.put(f"{BASE}/ticks", json={}), client.put(f"{BASE}/defaults", json={}),
        client.delete(f"{BASE}/overrides", params={"path": "x"}), client.get(f"{BASE}/destinations"),
        client.post(f"{BASE}/destinations", json={}), client.patch(f"{BASE}/destinations/{d}", json={}),
        client.delete(f"{BASE}/destinations/{d}"), client.put(f"{BASE}/destinations/{d}/extras", json={}),
    ]
    assert len(calls) == 10
    assert all(c.status_code in (401, 403) for c in calls), [c.status_code for c in calls]


def test_view_honors_locks_overrides_pause_and_webpush(service):
    client = make_client(service)
    dest = create(client)["destination"]["id"]
    client.put(f"{BASE}/ticks", json={"column": dest, "type_id": "session.finished", "value": False, "scope": "local"})
    client.put(f"{BASE}/settings", json={"paused": True})
    asyncio.run(service.destinations.seed_destination_ticks("webpush:abc", "webpush"))
    rows = [{"id": "abc", "endpoint": "https://fcm.googleapis.com/fcm/send/x"}]
    service.routing._subscriptions = lambda: rows
    v = service.routing.view()
    assert v.paused is True and v.revision == service.docs.revision
    assert v.is_ticked("screen", "session.permission") is True
    assert v.is_ticked(dest, "alert.notifications") is False
    assert v.is_ticked(dest, "session.finished") is False
    assert v.is_ticked(dest, "session.question") is True
    assert v.is_ticked("webpush:abc", "session.question") is True
    assert v.is_ticked("webpush:abc", "approval.folder_trust") is False
    ids = [d.id for d in v.destinations()]
    assert ids == [dest, "webpush:abc"]
    push = v.destinations()[1]
    assert (push.kind, push.scope, push.enabled, push.config, push.details) == ("webpush", "local", True, {}, False)
    assert v.is_ticked("nope", "session.finished") is False
    asyncio.run(service.routing.disable_locally(dest, "five failures"))
    assert not service.routing.view().destinations()[0].enabled
    doc = service.docs.snapshot()
    assert doc["global"][doc_model.dest_path(dest)]["val"]["enabled"] is True


def test_view_is_cached_by_revision(service):
    client = make_client(service)
    create(client)
    a = service.routing.view()
    assert service.routing.view() is a


def test_settings_body_shape_and_defaults_seeded(service):
    client = make_client(service)
    body = client.get(f"{BASE}/settings").json()
    assert set(body) == {"revision", "paused", "link", "defaults", "screen", "ticks", "destinations", "sync"}
    assert body["sync"] == {"available": False, "peers": []} and body["paused"] is False
    assert set(body["link"]) == {"kind", "base", "reason"}
    assert len(body["defaults"]) == len(types.TYPES) and sum(body["defaults"].values()) == len(types.seed_type_ids())
    put = client.put(f"{BASE}/defaults", json={"type_id": "session.finished", "value": False}).json()
    assert put["defaults"]["session.finished"] is False
    dest = create(client)["destination"]["id"]
    assert client.get(f"{BASE}/settings").json()["ticks"][dest]["session.finished"]["value"] is False


def test_install_id_and_counters(service):
    client = make_client(service)
    create(client)
    doc = service.docs.snapshot()
    me = doc["local"]["local/install_id"]
    assert me.startswith("n_")
    paths = [p for p in doc["global"] if p.startswith("dest/")]
    assert doc["global"][paths[0]]["ver"] == [1, me]
    client.patch(f"{BASE}/destinations/{doc_model.parse_path(paths[0]).dest}", json={"name": "z"})
    assert service.docs.snapshot()["global"][paths[0]]["ver"] == [2, me]
    assert not any(doc_model.is_local_only(p) for p in doc["global"])


def test_tombstones_pruned_on_write(service, config_path):
    from src.core.notifications.settings_doc.store import SettingsDocStore

    clock = {"t": 1000.0}
    store = SettingsDocStore(config_path, clock=lambda: clock["t"])
    p = doc_model.default_path("session.finished")
    store.update(lambda d, me: doc_model.delete_global(d, p, me, clock["t"]))
    assert "tomb" in store.snapshot()["global"][p]
    clock["t"] += doc_model.TOMBSTONE_TTL_SECONDS + 10
    store.update(lambda d, me: doc_model.set_local(d, doc_model.local_key("x"), 1))
    assert p not in store.snapshot()["global"]


def test_global_destination_cap(service, monkeypatch):
    from src.core.notifications.destinations import store as store_mod

    monkeypatch.setattr(store_mod, "MAX_GLOBAL_DESTINATIONS", 1)
    client = make_client(service)
    create(client)
    r = client.post(f"{BASE}/destinations", json=slack_body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "destination_limit"
    assert len(service.destinations._secrets._backend.items) == 1

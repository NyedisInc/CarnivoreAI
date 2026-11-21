
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import notification_route_routes as route_routes  # noqa: E402
from src.api import notification_settings_routes as set_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.notifications import doc_model, engine as eng, kind_specs, routing_view, types  # noqa: E402
from src.core.notifications.settings_doc import routes, styles_store, ticks, view  # noqa: E402
from src.core.notifications.sync import sanitize  # noqa: E402
from src.core.notifications.sync.peers import PeerInfo  # noqa: E402
from src.core.notifications.routing_view import DestinationView
from tests.python.notifications.engine_fakes import FakeSender, ev  # noqa: E402

BASE = "/api/v1/notifications"
ME, TOWER = "iid-nostromo", "iid-tower"
TYPE = "session.finished"
LOCKED = "alert.notifications"
PUSH = kind_specs.apns_destination_id("d_0123456789ab")


class FakeGateway:
    def __init__(self, peers):
        self._peers = peers

    async def roster(self):
        return list(self._peers)


def client_for(service, peers=(), authed=True) -> TestClient:
    app = FastAPI()
    app.include_router(route_routes.router, prefix="/api/v1")
    app.include_router(set_routes.router, prefix="/api/v1")
    app.state.notification_service = service
    app.state.notification_sync = SimpleNamespace(gateway=FakeGateway(peers)) if peers else None
    if authed:
        app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


@pytest.fixture
def bound(service):
    routes.migrate_legacy(service.docs, ME)
    return service


def peers():
    return [PeerInfo("k1", "tower", TOWER, True, 1)]


def _global(doc, prefix):
    return {p: e for p, e in doc["global"].items() if p.startswith(prefix)}


def test_resolve_fallback_matrix_for_self_and_another_computer(service):
    doc = service.docs.snapshot()
    row = types.get_type(TYPE)
    mine = lambda t: routes.resolve(doc, ME, ME, t, TYPE)  # noqa: E731
    assert mine("app").value is row.defaults.screen and mine("app").source == "default"
    assert mine("phone").value is False and mine("corner").value is True
    theirs = lambda t: routes.resolve(doc, ME, TOWER, t, TYPE)  # noqa: E731
    assert theirs("app").value is row.defaults.screen
    for target in ("desk", "phone", "corner"):
        assert theirs(target).value is None and theirs(target).source == "unknown"
    for iid in (ME, TOWER):
        for target in ("phone", "corner"):
            assert routes.resolve(doc, ME, iid, target, LOCKED).as_dict() == {"value": False, "source": "locked", "locked": True}
    assert routes.resolve(doc, ME, ME, "app", LOCKED).locked is False


def test_resolve_self_reads_legacy_keys_and_a_stored_route_wins(service):
    doc = doc_model.set_local(service.docs.snapshot(), doc_model.tick_path("desktop", TYPE), False)
    doc = doc_model.set_local(doc, doc_model.tick_path(PUSH, TYPE), True)
    doc = doc_model.set_local(doc, doc_model.corner_key(TYPE), False)
    assert [routes.resolve(doc, ME, ME, t, TYPE).value for t in ("desk", "phone", "corner")] == [False, True, False]
    doc = doc_model.set_global(doc, doc_model.route_path(ME, "phone", TYPE), False, ME)
    assert routes.resolve(doc, ME, ME, "phone", TYPE).as_dict() == {"value": False, "source": "global", "locked": False}


def test_put_routes_writes_one_commit_skips_locked_and_refuses_bad_input(bound):
    client = client_for(bound, peers())
    before = bound.docs.revision
    r = client.put(f"{BASE}/routes", json={"type_ids": [TYPE, "session.died", LOCKED], "computer": ME, "target": "phone", "value": True})
    assert r.status_code == 200, r.text
    assert bound.docs.revision == before + 1
    body = r.json()
    assert body["skipped"] == [LOCKED]
    assert body["types"][TYPE]["cells"][ME]["phone"] == {"value": True, "source": "global", "locked": False}
    assert body["types"][LOCKED]["locked"] == {"phone": True, "corner": True}
    doc = bound.docs.snapshot()
    assert doc_model.route_path(ME, "phone", LOCKED) not in doc["global"]
    assert [c["install_id"] for c in body["computers"]] == [ME, TOWER] and [c["hue"] for c in body["computers"]] == [0, 1]
    assert body["computers"][1]["syncs"] is True and body["self"] == ME and body["phone_paired"] is False
    ok = {"type_ids": [TYPE], "computer": TOWER, "target": "app", "value": False}
    assert client.put(f"{BASE}/routes", json=ok).status_code == 200
    assert client.put(f"{BASE}/routes", json={**ok, "computer": "iid-nobody"}).json() == {"detail": {"error": "unknown_computer"}}
    assert client.put(f"{BASE}/routes", json={**ok, "computer": "iid-nobody"}).status_code == 404
    for bad in ({**ok, "target": "fax"}, {**ok, "type_ids": ["no.such.type"]}):
        r = client.put(f"{BASE}/routes", json=bad)
        assert r.status_code == 422 and r.json() == {"detail": {"error": "bad_value"}}
    assert client.put(f"{BASE}/routes", json={**ok, "extra": 1}).status_code == 422


def test_every_new_route_refuses_unauthenticated(service):
    client = client_for(service, authed=False)
    calls = [client.get(f"{BASE}/routes"), client.put(f"{BASE}/routes", json={}), client.put(f"{BASE}/master", json={})]
    assert all(c.status_code in (401, 403) for c in calls), [c.status_code for c in calls]


def test_master_off_remembers_targets_and_blocks_every_column(bound):
    client = client_for(bound)
    for target, value in (("app", False), ("desk", True), ("phone", True)):
        assert client.put(f"{BASE}/routes", json={"type_ids": [TYPE], "computer": ME, "target": target, "value": value}).status_code == 200
    stored = lambda: json.dumps(_global(bound.docs.snapshot(), "route/"), sort_keys=True)  # noqa: E731
    snapshot = stored()
    rview = lambda: view.DocRoutingView(bound.docs.snapshot())  # noqa: E731
    assert rview().is_ticked("desktop", TYPE) and rview().is_ticked(PUSH, TYPE) and not rview().is_ticked("screen", TYPE)
    r = client.put(f"{BASE}/master", json={"type_ids": [TYPE], "value": False})
    assert r.status_code == 200 and r.json()["types"][TYPE]["on"] is False
    assert stored() == snapshot
    assert not any(rview().is_ticked(c, TYPE) for c in ("screen", "desktop", PUSH))
    assert client.put(f"{BASE}/master", json={"type_ids": [TYPE], "value": True}).json()["types"][TYPE]["on"] is True
    assert stored() == snapshot
    assert rview().is_ticked("desktop", TYPE) and rview().is_ticked(PUSH, TYPE) and not rview().is_ticked("screen", TYPE)
    assert client.put(f"{BASE}/master", json={"type_ids": ["no.such"], "value": True}).status_code == 422


def test_screen_and_desktop_ticks_and_corner_use_the_route_paths(bound):
    ticks.put_tick(bound.docs, "screen", TYPE, False)
    ticks.put_tick(bound.docs, "desktop", TYPE, False)
    styles_store.put_corner(bound.docs, TYPE, False)
    doc = bound.docs.snapshot()
    for target in ("app", "desk", "corner"):
        assert doc["global"][doc_model.route_path(ME, target, TYPE)]["val"] is False
    assert doc_model.tick_path("screen", TYPE) not in doc["global"] and doc_model.corner_key(TYPE) not in doc["local"]
    body = client_for(bound).get(f"{BASE}/settings").json()
    assert body["screen"][TYPE]["value"] is False and body["desktop"][TYPE]["value"] is False
    assert styles_store.corner(doc, TYPE) is False


def test_migration_writes_only_stored_legacy_cells_once(service):
    doc = service.docs.snapshot()
    service.docs.update(lambda d, me: doc_model.set_local(doc_model.set_local(
        doc_model.set_local(d, doc_model.tick_path("desktop", TYPE), False), doc_model.corner_key("session.died"), False),
        doc_model.tick_path(PUSH, "session.died"), True))
    service.docs.update(lambda d, me: doc_model.set_global(d, doc_model.tick_path("screen", TYPE), False, me))
    assert routes.migrate_legacy(service.docs, ME) == 4
    after = service.docs.snapshot()
    written = sorted(p for p in after["global"] if p.startswith("route/"))
    assert written == sorted([f"route/{ME}/desk/{TYPE}", f"route/{ME}/app/{TYPE}", f"route/{ME}/corner/session.died", f"route/{ME}/phone/session.died"])
    assert after["global"][f"route/{ME}/desk/{TYPE}"]["val"] is False and after["global"][f"route/{ME}/phone/session.died"]["val"] is True
    assert after["local"][doc_model.SELF_IID_KEY] == ME and after["local"][routes.MIGRATED_KEY] is True
    assert doc_model.tick_path("desktop", TYPE) in after["local"]
    rev = service.docs.revision
    assert routes.migrate_legacy(service.docs, ME) == 0 and service.docs.revision == rev
    assert not any(TOWER in p for p in after["global"])


def test_migration_of_an_untouched_computer_writes_no_route(service):
    assert routes.migrate_legacy(service.docs, ME) == 0
    assert not [p for p in service.docs.snapshot()["global"] if p.startswith("route/")]


def test_sync_sanitizer_and_a_peer_route_appears_in_get_routes(bound):
    entry = {"val": True, "ver": [1, TOWER]}
    good = {f"route/{TOWER}/phone/{TYPE}": entry, f"on/{TYPE}": {"val": False, "ver": [1, TOWER]}}
    assert sanitize.clean_map(good, 0.0) == good
    bad = {f"route/a%2Fb/phone/{TYPE}": entry, f"route/{TOWER}/fax/{TYPE}": entry, f"route/{TOWER}/phone/no.such": entry,
           f"route/{TOWER}/phone/{TYPE}x": entry, f"route/{TOWER}/phone/{TYPE}/x": entry, "on/no.such": entry,
           f"on/{TYPE}": {"val": "yes", "ver": [1, TOWER]}, f"route/{TOWER}/phone/{TYPE}": {"val": 1, "ver": [1, TOWER]}}
    assert sanitize.clean_map(bad, 0.0) == {}
    merged = doc_model.merge_global(bound.docs.snapshot()["global"], sanitize.clean_map(good, 0.0))
    bound.docs.update(lambda d, me: {**d, "global": merged})
    body = client_for(bound, peers()).get(f"{BASE}/routes").json()
    assert body["types"][TYPE]["cells"][TOWER]["phone"] == {"value": True, "source": "global", "locked": False}
    assert body["types"][TYPE]["on"] is False
    assert body["types"][TYPE]["cells"][TOWER]["desk"]["source"] == "unknown"


@pytest.fixture
def _engine_clean():
    routing_view.uninstall_routing()
    eng.install_engine(None)
    yield
    routing_view.uninstall_routing()
    eng.install_engine(None)


@pytest.mark.asyncio
async def test_each_computer_sends_the_phone_push_for_its_own_sessions(bound, _engine_clean):
    from unittest import mock

    sender = FakeSender()
    push = DestinationView(id=PUSH, kind="apns", name="phone", enabled=True, scope="local", config={})

    async def secrets(_id):
        return {}

    async def link_base():
        return ""

    engine = eng.NotifyEngine(sender_lookup=lambda kind: sender, is_muted=lambda s: False, secrets_lookup=secrets, link_base=link_base,
                              computer_name=lambda: "nostromo")
    routing_view.install_routing(lambda: view.DocRoutingView(bound.docs.snapshot(), [push]), SimpleNamespace())
    put = lambda iid, value: routes.put_routes(bound.docs, [TYPE], iid, "phone", value, ME, [TOWER])  # noqa: E731
    with mock.patch.object(eng.alert_service, "raise_alert"), mock.patch.object(eng.resource_push, "notify"):
        put(ME, False)
        put(TOWER, True)
        await engine.handle(ev(TYPE))
        await engine.join()
        assert sender.calls == []
        put(ME, True)
        await engine.handle(ev(TYPE))
        await engine.join()
        assert len(sender.calls) == 1
        await engine.handle(ev(TYPE, session_id="remote:peer-1"))
        await engine.join()
        assert len(sender.calls) == 1
    await asyncio.sleep(0)


def test_per_device_push_tick_stays_its_own_and_master_off_blocks_screen_desktop_corner(service):
    other = kind_specs.apns_destination_id("d_ba9876543210")
    service.docs.update(lambda d, me: doc_model.set_local(doc_model.set_local(d, doc_model.tick_path(PUSH, TYPE), True), doc_model.tick_path(other, TYPE), False))
    routes.migrate_legacy(service.docs, ME)
    doc = service.docs.snapshot()
    assert not [p for p in doc["global"] if "/phone/" in p]
    rv = view.DocRoutingView(doc)
    assert rv.is_ticked(PUSH, TYPE) and not rv.is_ticked(other, TYPE)
    service.docs.update(lambda d, me: doc_model.set_global(d, doc_model.on_path("session.died"), False, me))
    doc = service.docs.snapshot()
    assert not view.cell(doc, "screen", "session.died").value and not view.cell(doc, "desktop", "session.died").value
    assert styles_store.corner(doc, "session.died") is False

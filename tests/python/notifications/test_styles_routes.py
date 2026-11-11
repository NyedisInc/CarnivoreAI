
from __future__ import annotations

import json
import time

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import notification_settings_routes as set_routes  # noqa: E402
from src.api import notification_test_routes as test_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.notifications import doc_model, styles, types  # noqa: E402
from src.core.notifications import engine as eng  # noqa: E402
from src.core.notifications.destinations.service import NotificationService  # noqa: E402
from src.core.notifications.sync import sanitize  # noqa: E402
from tests.python.notifications.engine_fakes import dest  # noqa: E402
from tests.python.notifications.test_engine import Rig  # noqa: E402

BASE = "/api/v1/notifications"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from src.core.notifications.settings_doc import store as store_mod

    monkeypatch.setattr(store_mod.resource_push, "notify", lambda *a, **k: None)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"agents": {}}))
    service = NotificationService(cfg)
    app = FastAPI()
    app.include_router(set_routes.router, prefix="/api/v1")
    app.include_router(test_routes.router, prefix="/api/v1")
    app.state.notification_service = service
    app.dependency_overrides[require_auth] = lambda: None
    styles.install_source(service.docs.snapshot)
    c = TestClient(app)
    c.service = service
    yield c
    styles.install_source(None)


def test_put_then_get_round_trip_and_effective_style(client):
    first = client.get(f"{BASE}/styles").json()["styles"]["session.died"]
    assert first == {"sound": "alarm", "urgency": "time-sensitive", "source": "default", "corner": True}
    r = client.put(f"{BASE}/styles/session.died", json={"sound": "soft", "urgency": "passive", "corner": False})
    assert r.status_code == 200, r.text
    got = client.get(f"{BASE}/styles").json()["styles"]["session.died"]
    assert got == {"sound": "soft", "urgency": "passive", "source": "global", "corner": False}
    assert styles.effective_style("session.died") == styles.Style(sound="soft", level="p")
    client.put(f"{BASE}/styles/session.died", json={"sound": "done"})
    assert client.get(f"{BASE}/styles").json()["styles"]["session.died"]["urgency"] == "passive"


@pytest.mark.parametrize("body", [{"sound": "klaxon"}, {"urgency": "loud"}, {"corner": "maybe"}, {"x": 1}, {}])
def test_bad_values_are_422(client, body):
    assert client.put(f"{BASE}/styles/session.died", json=body).status_code == 422


def test_unknown_type_is_422(client):
    assert client.put(f"{BASE}/styles/not.a.type", json={"sound": "ask"}).status_code == 422


def test_desktop_tick_round_trips_and_is_never_synced(client):
    row = client.get(f"{BASE}/settings").json()["desktop"]
    assert row["session.finished"] == {"value": True, "source": "default", "locked": False}
    assert row["swarm.alert"]["value"] is False
    r = client.put(f"{BASE}/ticks", json={"column": "desktop", "type_id": "session.finished", "value": False})
    assert r.status_code == 200, r.text
    assert client.get(f"{BASE}/settings").json()["desktop"]["session.finished"]["value"] is False
    doc = client.service.docs.snapshot()
    assert doc_model.tick_path("desktop", "session.finished") in doc["local"]
    assert not any("desktop" in p for p in doc["global"])
    planted = {doc_model.tick_path("desktop", "session.finished"): {"val": True, "ver": [9, "n_peer"]}}
    assert sanitize.clean_map(planted, time.time()) == {}


def test_styles_sync_globally_and_corner_stays_local(client):
    client.put(f"{BASE}/styles/session.finished", json={"sound": "ask", "urgency": "time-sensitive", "corner": False})
    doc = client.service.docs.snapshot()
    synced = sanitize.clean_map(doc["global"], time.time())
    assert synced[doc_model.style_path("session.finished")]["val"] == {"sound": "ask", "urgency": "time-sensitive"}
    assert "corner" not in json.dumps(doc["global"]) and "corner" not in json.dumps(synced)
    assert doc["local"][doc_model.corner_key("session.finished")] is False
    bad = {doc_model.style_path("session.finished"): {"val": {"sound": "nope", "urgency": "active"}, "ver": [1, "n_peer"]}}
    assert sanitize.clean_map(bad, time.time()) == {}


@pytest.mark.asyncio
async def test_test_send_of_a_type_builds_its_sample_card(client):
    client.put(f"{BASE}/styles/session.died", json={"sound": "soft"})
    rig = Rig([dest(kind="apns")])
    eng.install_engine(rig.engine)
    try:
        assert client.post(f"{BASE}/destinations/d_000000000001/test", json={"type_id": "nope"}).status_code == 422
        r = client.post(f"{BASE}/destinations/d_000000000001/test", json={"type_id": "session.died"})
        assert r.status_code == 200 and r.json()["ok"] is True
        event = rig.sender.calls[0][0]
        assert event.type_id == "session.died"
        hint = event.card_hint
        assert hint["sample"] is True and hint["kind"] == "died" and hint["snd"] == "soft" and hint["lv"] == "t"
        assert hint["card"]["strip"][0] == "died"
    finally:
        eng.install_engine(None)
    assert types.is_registered("session.died")


from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import app_alerts_routes as routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.app_alerts import conditions, kinds, service  # noqa: E402
from src.core.app_alerts import constants as K  # noqa: E402
from src.core.db import db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402

BASE = "/api/v1/alerts"
TITLE = "app_alert.pipeline.llm_all_down.title"
KEY_LLM_ALL_DOWN = "pipeline.llm_all_down"


@pytest.fixture()
def world(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    db = db_path_for(state)
    frames: list = []
    service.configure(db, frames.append)
    monkeypatch.setattr(routes, "_db_path", lambda: db)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    yield SimpleNamespace(client=TestClient(app), app=app, db=db, frames=frames)
    service.configure(None, None)


def _raise(**kw):
    args = dict(source="conversation_index", severity=K.SEV_ERROR, title_key=TITLE, params={"waiting": 3})
    args.update(kw)
    return service.raise_alert(KEY_LLM_ALL_DOWN, **args)


def test_every_route_requires_auth(world):
    world.app.dependency_overrides.clear()
    client = TestClient(world.app)
    for method, path, body in [("get", BASE, None), ("post", f"{BASE}/1/dismiss", None),
                               ("post", f"{BASE}/1/snooze", {"minutes": 5}), ("post", f"{BASE}/dismiss-resolved", None),
                               ("post", f"{BASE}/widget-report", {"widget": "core.notes", "zone": "home",
                                                                   "w": 2, "h": 1, "reason": "too-small"})]:
        response = client.request(method.upper(), path, json=body)
        assert response.status_code in (401, 403), path


def test_raise_dedupes_into_one_row_with_a_count(world):
    first = _raise()
    second = _raise(params={"waiting": 5})
    assert first["id"] == second["id"] and second["count"] == 2 and second["params"] == {"waiting": 5}
    assert second["first_seen"] <= second["last_seen"]
    body = world.client.get(BASE).json()
    assert len(body["alerts"]) == 1 and body["counts"] == {"error": 1, "warn": 0, "info": 0}
    assert [f["type"] for f in world.frames] == [K.FRAME_RAISED, K.FRAME_UPDATED]
    assert set(world.frames[0]) == {"type", "id", "key", "severity", "state", "count", "notify_type"}


def test_strings_are_catalog_keys_and_a_bad_raise_never_raises(world):
    assert _raise(title_key="Server is down") is None
    assert _raise(severity="fatal") is None
    assert world.client.get(BASE).json()["alerts"] == []


def test_resolve_closes_and_the_next_raise_is_a_new_incident(world):
    first = _raise()
    resolved = service.resolve(KEY_LLM_ALL_DOWN)
    assert [r["state"] for r in resolved] == [K.STATE_RESOLVED]
    assert world.frames[-1]["type"] == K.FRAME_RESOLVED
    assert world.client.get(BASE).json()["counts"]["error"] == 0
    again = _raise()
    assert again["id"] != first["id"] and again["count"] == 1
    everything = world.client.get(BASE, params={"state": "all"}).json()["alerts"]
    assert [a["state"] for a in everything] == [K.STATE_ACTIVE, K.STATE_RESOLVED]


def test_sticky_survives_resolve_until_dismissed(world):
    row = service.raise_alert("pipeline.capture_corrupt:c1", source="pipeline", severity=K.SEV_ERROR,
                              title_key=TITLE, sticky=True, auto_resolve=False)
    assert service.resolve("pipeline.capture_corrupt:c1") == []
    assert world.client.post(f"{BASE}/{row['id']}/dismiss").json()["state"] == K.STATE_DISMISSED
    assert world.client.get(BASE).json()["alerts"] == []


def test_dismiss_absorbs_raises_until_the_condition_clears(world):
    row = _raise()
    assert world.client.post(f"{BASE}/{row['id']}/dismiss").json()["state"] == K.STATE_DISMISSED
    frames_before = len(world.frames)
    assert _raise()["id"] == row["id"]
    assert len(world.frames) == frames_before and world.client.get(BASE).json()["alerts"] == []
    service.resolve(KEY_LLM_ALL_DOWN)
    assert _raise()["id"] != row["id"]


def test_snooze_hides_from_the_badge_and_routes_answer_404_409(world):
    row = _raise()
    snoozed = world.client.post(f"{BASE}/{row['id']}/snooze", json={"minutes": 30}).json()
    assert snoozed["state"] == K.STATE_SNOOZED and snoozed["snoozed_until"]
    body = world.client.get(BASE).json()
    assert body["counts"]["error"] == 0 and body["alerts"][0]["state"] == K.STATE_SNOOZED
    assert world.client.post(f"{BASE}/{row['id']}/snooze", json={"minutes": 0}).status_code == 422
    assert world.client.post(f"{BASE}/999/dismiss").status_code == 404
    service.resolve(KEY_LLM_ALL_DOWN)
    assert world.client.post(f"{BASE}/{row['id']}/snooze", json={"minutes": 5}).status_code == 409
    assert world.client.post(f"{BASE}/dismiss-resolved").json() == {"dismissed": 1}


def test_condition_registry_raises_clears_and_a_failing_probe_changes_nothing(world):
    answers = iter([conditions.Active(severity=K.SEV_WARN, title_key=TITLE), RuntimeError("probe broke"),
                    conditions.CLEAR])

    def probe():
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    conditions.register_condition("disk.low:/", probe, 1, source="disk")
    try:
        assert conditions.run_due(now=0) == ["disk.low:/"]
        assert world.client.get(BASE).json()["counts"]["warn"] == 1
        assert conditions.run_due(now=10) == []
        assert world.client.get(BASE).json()["counts"]["warn"] == 1
        assert conditions.run_due(now=20) == ["disk.low:/"]
        assert world.client.get(BASE).json()["counts"]["warn"] == 0
    finally:
        conditions.unregister_condition("disk.low:/")


def test_widget_report_raises_one_warn_per_widget_zone_and_size(world):
    body = {"widget": "core.notes", "zone": "home", "w": 2, "h": 1, "reason": "too-small"}
    first = world.client.post(f"{BASE}/widget-report", json=body).json()
    again = world.client.post(f"{BASE}/widget-report", json=body).json()
    other = world.client.post(f"{BASE}/widget-report", json={**body, "w": 3}).json()
    assert first["id"] == again["id"] and again["count"] == 2 and other["id"] != first["id"]
    assert first["key"] == "app_alert.widget.core.notes.home.2x1" and first["severity"] == K.SEV_WARN
    assert first["detail_key"] == "app_alert.widget.report.detail.too_small"
    assert world.client.get(BASE).json()["counts"]["warn"] == 2
    for bad in ({**body, "zone": "kitchen"}, {**body, "widget": "Notes"}, {**body, "w": -1}, {**body, "reason": "x"}):
        assert world.client.post(f"{BASE}/widget-report", json=bad).status_code == 422


def test_list_carries_the_sender_registry(world):
    body = world.client.get(BASE).json()
    assert body["sources"] == kinds.source_catalog()

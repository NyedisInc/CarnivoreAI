
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.config  # noqa: F401
from src.api import automation_routes
from src.api.auth import require_auth
from src.core.automations import gates, pause
from src.core.automations import models as m
from src.core.resource_push import topics

AUTOMATION = {"automation_id": "aut_1", "enabled": True, "target": {"kind": "recipe", "recipe": "no_such"}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"keep_me": 1}))
    monkeypatch.setattr(pause, "config_path", lambda: path)
    announced = []
    monkeypatch.setattr(pause.resource_push, "notify", announced.append)
    return path, announced


def _client():
    app = FastAPI()
    app.include_router(automation_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def test_put_stores_the_flag_beside_other_keys_and_announces(world):
    path, announced = world
    client = _client()
    assert client.get("/api/v1/automations/scheduler").json() == {"paused": False}
    assert client.put("/api/v1/automations/scheduler", json={"paused": True}).json() == {"paused": True}
    assert json.loads(path.read_text()) == {"keep_me": 1, "automations_paused": True}
    assert announced == [topics.AUTOMATIONS]
    assert client.get("/api/v1/automations/scheduler").json() == {"paused": True}
    client.put("/api/v1/automations/scheduler", json={"paused": True})
    assert announced == [topics.AUTOMATIONS]
    assert client.put("/api/v1/automations/scheduler", json={"paused": False}).json() == {"paused": False}
    assert pause.is_paused() is False


def test_put_refuses_a_non_boolean_and_an_unwritable_config(world, monkeypatch):
    path, _ = world
    client = _client()
    assert client.put("/api/v1/automations/scheduler", json={"paused": "yes"}).status_code == 422
    path.unlink()
    response = client.put("/api/v1/automations/scheduler", json={"paused": True})
    assert response.status_code == 503 and response.json()["detail"]["code"] == "config_unwritable"


def test_a_paused_scheduler_skips_scheduled_runs_only(world):
    pause.set_paused(True)
    verdict, _ = gates.evaluate(AUTOMATION, {"run_id": "r1", "trigger": "schedule"}, [])
    assert verdict == gates.Verdict(m.SKIPPED, m.R_PAUSED)
    verdict, _ = gates.evaluate(AUTOMATION, {"run_id": "r2", "trigger": "run_now"}, [])
    assert verdict != gates.Verdict(m.SKIPPED, m.R_PAUSED)
    pause.set_paused(False)
    verdict, _ = gates.evaluate(AUTOMATION, {"run_id": "r3", "trigger": "schedule"}, [])
    assert verdict != gates.Verdict(m.SKIPPED, m.R_PAUSED)


from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import app_update_routes
from src.api.auth import require_auth
from src.config import settings
from src.core import resource_push
from src.core.app_update import store
from src.core.version import resolve_version
from src.core.resource_push.topics import APP_UPDATE, RESOURCE_TOPICS

API = "/api/v1/app-update"


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"updates": {"feed_url": "https://u.example/app"}, "other": 1}))
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    announced = []
    monkeypatch.setattr(resource_push, "notify", lambda topic, *a, **k: announced.append(topic))
    store.reset_for_tests()
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None
    app.include_router(app_update_routes.router, prefix="/api/v1")
    c = TestClient(app)
    c.cfg, c.announced = cfg, announced
    yield c
    store.reset_for_tests()


def test_topic_is_advertised():
    assert APP_UPDATE in RESOURCE_TOPICS


def test_fresh_status_is_detached_and_auto_update_is_off(client):
    body = client.get(API).json()
    assert body["attached"] is False and body["state"] == "unavailable"
    assert body["auto_update"] is False
    assert body["current_version"] == resolve_version() != ""


def test_toggle_writes_config_keeps_siblings_and_announces(client):
    assert client.put(f"{API}/auto-update", json={"enabled": True}).json()["auto_update"] is True
    doc = json.loads(client.cfg.read_text())
    assert doc["updates"] == {"feed_url": "https://u.example/app", "auto_update": True} and doc["other"] == 1
    assert APP_UPDATE in client.announced
    assert client.put(f"{API}/auto-update", json={"enabled": False}).json()["auto_update"] is False
    assert client.put(f"{API}/auto-update", json={"enabled": "yes"}).status_code == 422


def test_check_and_install_need_an_attached_app(client):
    assert client.post(f"{API}/check").status_code == 409
    assert client.post(f"{API}/install").status_code == 409


def test_report_then_commands(client):
    assert client.post(f"{API}/state", json={"state": "bogus"}).status_code == 422
    assert client.post(f"{API}/state", json={"state": "update_refused", "detail": "not newer"}).status_code == 200
    client.announced.clear()
    r = client.post(f"{API}/state", json={"state": "current", "current_version": "1.16.2"})
    assert r.json()["attached"] is True and client.announced == [APP_UPDATE]
    assert client.post(f"{API}/install").status_code == 409
    seq = client.post(f"{API}/check").json()
    assert seq["command"] == "check" and seq["command_seq"] == 1
    client.post(f"{API}/state", json={"state": "available", "current_version": "1.16.2", "latest_version": "1.16.3"})
    body = client.post(f"{API}/install").json()
    assert body["command"] == "install" and body["command_seq"] == 2 and body["latest_version"] == "1.16.3"

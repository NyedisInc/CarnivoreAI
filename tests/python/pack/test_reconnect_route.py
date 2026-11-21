
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import pack_machines_routes
from src.api.auth import require_auth
from src.core.computers import runtime as computers_runtime


def _client(config_path) -> TestClient:
    app = FastAPI()
    app.include_router(pack_machines_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{}")
    calls = []

    async def switched() -> None:
        calls.append(1)

    rt = SimpleNamespace(config_path=path, relay_switch_changed=switched, calls=calls)
    monkeypatch.setattr(computers_runtime, "active", lambda: rt)
    return rt


def test_get_reports_the_choice_and_what_is_in_force(runtime) -> None:
    body = _client(runtime.config_path).get("/api/v1/pack/reconnect").json()
    assert body["relay"] is None and set(body) == {"relay", "relay_on", "takeover_on"}


def test_put_stores_the_choice_applies_it_and_get_reads_it_back(runtime) -> None:
    client = _client(runtime.config_path)
    put = client.put("/api/v1/pack/reconnect", json={"relay": False, "takeover": True})
    assert put.status_code == 200
    assert put.json()["relay"] is False and put.json()["relay_on"] is False and put.json()["takeover_on"] is True
    assert runtime.calls == [1]
    assert client.get("/api/v1/pack/reconnect").json() == put.json()
    assert "relay" in json.dumps(json.loads(runtime.config_path.read_text()))


def test_both_answer_503_when_the_computers_runtime_is_not_running(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(computers_runtime, "active", lambda: None)
    client = _client(tmp_path / "config.json")
    assert client.get("/api/v1/pack/reconnect").status_code == 503
    assert client.put("/api/v1/pack/reconnect", json={"relay": True}).status_code == 503

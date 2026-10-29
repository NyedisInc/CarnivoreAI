
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import developer_mode
from src.cplugs.host import routes as host_routes, runtime, state as owner_state
from tests.python.cplugs.owner import turn_on


@pytest.fixture
def dev_switch(monkeypatch: pytest.MonkeyPatch) -> dict:
    switch = {"on": False}
    monkeypatch.setattr(developer_mode, "is_on", lambda: switch["on"])
    return switch


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def test_tmdevtools_is_the_dev_tier_plugin() -> None:
    assert runtime.find("tmdevtools").manifest.tier == "dev"
    assert [d.id for d in runtime.definitions() if d.manifest.tier == "dev"] == ["tmdevtools", "devwidgetlab"]


def test_dev_plugin_is_off_hidden_and_not_started_until_developer_mode_is_on(client: TestClient, dev_switch: dict) -> None:
    host = runtime.host_for(client.app)
    turn_on(host, "huddle")
    turn_on(host, "tmdevtools")
    definition = runtime.find("tmdevtools")

    ids = [row["id"] for row in client.get("/api/v1/cplugs").json()["cplugs"]]
    assert "tmdevtools" not in ids and "huddle" in ids, "off: hidden from the list, ordinary plugins untouched"
    assert host.enabled("tmdevtools") is False
    assert client.get("/api/v1/cplugs/tmdevtools").status_code == 404
    assert client.put("/api/v1/cplugs/tmdevtools", json={"enabled": True, "revision": 0}).status_code == 404
    stored = owner_state.stored_entry(host.state_dir, "tmdevtools")
    assert stored is not None and stored["enabled"] is True, "nothing is deleted or rewritten by the gate"

    dev_switch["on"] = True
    rows = {row["id"]: row for row in client.get("/api/v1/cplugs").json()["cplugs"]}
    assert rows["tmdevtools"]["enabled"] is True and rows["tmdevtools"]["tier"] == "dev", "on: back, as the owner had it"
    assert host.enabled("tmdevtools") is True
    assert "tmdevtools" not in {d.id for d in runtime.listed() if runtime.hidden(d)}
    assert definition is not None


def test_a_hidden_dev_plugin_is_not_a_dependent_of_the_task_manager(client: TestClient, dev_switch: dict) -> None:
    host = runtime.host_for(client.app)
    turn_on(host, "huddle")
    turn_on(host, "tmdevtools")
    needed_by = lambda: {n["id"] for n in client.get("/api/v1/cplugs/huddle").json()["dependencies"]["needed_by"]}
    assert "tmdevtools" not in needed_by()
    dev_switch["on"] = True
    assert "tmdevtools" in needed_by()


def test_developer_mode_reads_off_on_a_fresh_config_and_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import settings

    def unreadable(self: object) -> None:
        raise FileNotFoundError("config.json")

    monkeypatch.setattr(type(settings), "load_auth_config", unreadable)
    assert developer_mode.is_on() is False


def test_widget_lab_is_hidden_and_off_until_developer_mode_is_on(client: TestClient, dev_switch: dict) -> None:
    host = runtime.host_for(client.app)
    turn_on(host, "devwidgetlab")
    assert runtime.find("devwidgetlab").manifest.tier == "dev"
    assert "devwidgetlab" not in [row["id"] for row in client.get("/api/v1/cplugs").json()["cplugs"]]
    assert host.enabled("devwidgetlab") is False
    assert client.get("/api/v1/cplugs/devwidgetlab").status_code == 404
    assert owner_state.stored_entry(host.state_dir, "devwidgetlab")["enabled"] is True, "the gate deletes nothing"

    dev_switch["on"] = True
    rows = {row["id"]: row for row in client.get("/api/v1/cplugs").json()["cplugs"]}
    assert rows["devwidgetlab"]["tier"] == "dev" and rows["devwidgetlab"]["enabled"] is True
    assert host.enabled("devwidgetlab") is True

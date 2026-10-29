
from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_autosleep_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_autosleep_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import auto_sleep_routes
from src.api.auth import require_auth
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.models.websocket import WSMessageType


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.core import session_change_notice

    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"keep": 1}))
    monkeypatch.setattr(auto_sleep_routes, "_config_path", lambda: config)
    monkeypatch.setattr(auto_sleep_routes, "_db_path", lambda: db_path_for(state))
    frames = []
    monkeypatch.setattr(
        session_change_notice, "get_hub",
        lambda _state: SimpleNamespace(publish=lambda f: frames.append(f) or 1),
    )
    with connect(db_path_for(state), create=False) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, "
            "tmux_created_epoch, working_dir, title, origin, lifecycle, "
            "lifecycle_source, agent_type, created_at, updated_at) VALUES "
            "('row-uuid-api', 'cloude', 'carnivore_api', 1790090835, '/Users/x/p', "
            "'t', 'created', 'running', 'tmux_list', 'claude', "
            "'2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')"
        )
        conn.commit()
    app = FastAPI()
    app.include_router(auto_sleep_routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return SimpleNamespace(client=TestClient(app), config=config, frames=frames, app=app)


def test_get_answers_the_owners_default(world):
    got = world.client.get("/auto-sleep").json()
    assert got["enabled"] is True and got["idle_minutes"] == 60
    assert got["keep_awake"] == [] and got["min_idle_minutes"] == 5


def test_put_writes_and_publishes(world):
    got = world.client.put("/auto-sleep", json={"enabled": False, "idle_minutes": 45}).json()
    assert got["enabled"] is False and got["idle_minutes"] == 45
    doc = json.loads(world.config.read_text())
    assert doc["auto_sleep"]["idle_minutes"] == 45 and doc["keep"] == 1
    assert world.frames == [{"type": WSMessageType.AUTO_SLEEP_CHANGED}]


def test_put_refuses_minutes_out_of_range(world):
    before = world.config.read_text()
    response = world.client.put("/auto-sleep", json={"idle_minutes": 2})
    assert response.status_code == 422
    assert world.config.read_text() == before


def test_keep_awake_by_name_stores_the_uuid_and_answers_the_name(world):
    got = world.client.put(
        "/auto-sleep/keep-awake", json={"tmux_name": "carnivore_api", "keep_awake": True}
    ).json()
    assert got["keep_awake"] == ["carnivore_api"]
    assert got["keep_awake_session_uuids"] == ["row-uuid-api"]
    assert json.loads(world.config.read_text())["auto_sleep"]["keep_awake"] == ["row-uuid-api"]
    got = world.client.put(
        "/auto-sleep/keep-awake", json={"session_uuid": "row-uuid-api", "keep_awake": False}
    ).json()
    assert got["keep_awake"] == []


def test_keep_awake_unknown_name_is_404_and_writes_nothing(world):
    before = world.config.read_text()
    response = world.client.put(
        "/auto-sleep/keep-awake", json={"tmux_name": "nobody", "keep_awake": True}
    )
    assert response.status_code == 404
    assert world.config.read_text() == before


def test_keep_awake_needs_exactly_one_name(world):
    both = world.client.put("/auto-sleep/keep-awake", json={
        "tmux_name": "carnivore_api", "session_uuid": "row-uuid-api", "keep_awake": True})
    neither = world.client.put("/auto-sleep/keep-awake", json={"keep_awake": True})
    assert both.status_code == 422 and neither.status_code == 422


def test_the_retired_per_device_pins_route_is_gone(world):
    got = world.client.put("/auto-sleep/pins", json={
        "device_id": "device-1234", "names": ["carnivore_api"]})
    assert got.status_code in (404, 405)
    assert "pinned_by_device" not in json.loads(world.config.read_text()).get("auto_sleep", {})


class _FakeGuard:

    def __init__(self, active: bool = False) -> None:
        self.active = active
        self.counts: list[int] = []

    def reconcile(self, count: int) -> None:
        self.counts.append(count)
        self.active = count > 0


def test_mac_awake_is_read_from_the_guard_on_every_get(world):
    assert world.client.get("/auto-sleep").json()["mac_awake"] is False
    world.app.state.mac_awake_guard = _FakeGuard(active=True)
    assert world.client.get("/auto-sleep").json()["mac_awake"] is True
    world.app.state.mac_awake_guard.active = False
    assert world.client.get("/auto-sleep").json()["mac_awake"] is False


def test_keep_awake_writes_reconcile_the_guard_and_answer_its_state(world):
    guard = _FakeGuard()
    world.app.state.mac_awake_guard = guard
    on = world.client.put(
        "/auto-sleep/keep-awake", json={"tmux_name": "carnivore_api", "keep_awake": True}
    ).json()
    assert guard.counts == [1] and on["mac_awake"] is True
    off = world.client.put(
        "/auto-sleep/keep-awake", json={"tmux_name": "carnivore_api", "keep_awake": False}
    ).json()
    assert guard.counts == [1, 0] and off["mac_awake"] is False
    assert world.client.get("/auto-sleep").json()["mac_awake"] is False


def test_every_route_requires_auth(world):
    world.app.dependency_overrides.clear()
    client = TestClient(world.app)
    assert client.get("/auto-sleep").status_code in (401, 403)
    assert client.put("/auto-sleep", json={"enabled": False}).status_code in (401, 403)
    assert client.put(
        "/auto-sleep/keep-awake", json={"tmux_name": "carnivore_api", "keep_awake": True}
    ).status_code in (401, 403)


def test_unread_settings_default_to_off_and_sixty_minutes(world):
    got = world.client.get("/auto-sleep").json()
    assert got["unread_blocks_sleep"] is False and got["unread_idle_minutes"] == 60


def test_unread_settings_round_trip_through_the_store(world):
    got = world.client.put(
        "/auto-sleep", json={"unread_blocks_sleep": False, "unread_idle_minutes": 240}
    ).json()
    assert got["unread_blocks_sleep"] is False and got["unread_idle_minutes"] == 240
    on_disk = json.loads(world.config.read_text())["auto_sleep"]
    assert on_disk["unread_blocks_sleep"] is False and on_disk["unread_idle_minutes"] == 240
    assert on_disk["idle_minutes"] == 60, "an omitted field is left alone"
    assert world.frames[-1]["type"] == WSMessageType.AUTO_SLEEP_CHANGED


def test_unread_idle_minutes_out_of_range_is_refused_and_writes_nothing(world):
    before = world.config.read_text()
    res = world.client.put("/auto-sleep", json={"unread_idle_minutes": 1})
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_unread_idle_minutes"
    assert world.config.read_text() == before


from __future__ import annotations

import json
import os
import tempfile
from typing import List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tray_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tray_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import auto_sleep_routes, autonomy_routes
from src.api.auth import require_auth
from src.core.auto_sleep.mac_awake import reconcile_at_boot


class FakeGuard:

    def __init__(self) -> None:
        self.calls: List[int] = []
        self.active = False

    def reconcile(self, count: int) -> None:
        self.calls.append(count)
        self.active = count > 0


@pytest.fixture()
def keep(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"other": 1}))
    monkeypatch.setattr(auto_sleep_routes, "_config_path", lambda: config)
    monkeypatch.setattr(auto_sleep_routes, "_changed", lambda request: None)
    app = FastAPI()
    app.include_router(auto_sleep_routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.state.mac_awake_guard = FakeGuard()
    return type("K", (), {"client": TestClient(app), "config": config, "app": app})()


def test_keep_awake_defaults_off_then_persists_and_reconciles(keep):
    assert keep.client.get("/system/keep-awake").json() == {"always": False}
    assert keep.client.put("/system/keep-awake", json={"always": True}).json() == {"always": True}
    assert keep.app.state.mac_awake_guard.calls == [1]
    doc = json.loads(keep.config.read_text())
    assert doc["auto_sleep"]["mac_awake_always"] is True and doc["other"] == 1
    assert keep.client.get("/system/keep-awake").json() == {"always": True}
    keep.client.put("/system/keep-awake", json={"always": False})
    assert keep.app.state.mac_awake_guard.calls == [1, 0]


def test_boot_reconcile_honors_the_persisted_flag(keep):
    keep.client.put("/system/keep-awake", json={"always": True})
    fresh = FakeGuard()
    reconcile_at_boot(fresh, keep.config)
    assert fresh.calls == [1]


def test_demand_adds_to_the_session_list(keep):
    from src.config.auto_sleep import AutoSleepConfig

    assert AutoSleepConfig(keep_awake=["a1b2c3d4"], mac_awake_always=True).mac_awake_demand() == 2
    assert AutoSleepConfig().mac_awake_demand() == 0


def test_keep_awake_rejects_bad_body_and_missing_config(keep):
    assert keep.client.put("/system/keep-awake", json={"always": "yes"}).status_code == 422
    assert keep.client.put("/system/keep-awake", json={}).status_code == 422
    keep.config.unlink()
    assert keep.client.put("/system/keep-awake", json={"always": True}).status_code == 500


def test_keep_awake_requires_auth(keep):
    keep.app.dependency_overrides.clear()
    client = TestClient(keep.app)
    assert client.get("/system/keep-awake").status_code in (401, 403)
    assert client.put("/system/keep-awake", json={"always": True}).status_code in (401, 403)


@pytest.fixture()
def stand(monkeypatch):
    calls: List[str] = []

    async def beast(body, source):
        assert source == "stand_down"
        calls.append(f"beast:{body.enabled}")
        return {"enabled": False}

    async def swarm(_state, enabled):
        calls.append(f"swarm:{enabled}")
        return {"enabled": enabled}

    def pause(paused):
        calls.append(f"pause:{paused}")
        return paused

    monkeypatch.setattr(autonomy_routes.beast_mode_routes, "set_beast_mode", beast)
    monkeypatch.setattr(autonomy_routes.switch, "set_enabled", swarm)
    monkeypatch.setattr(autonomy_routes.pause, "set_paused", pause)
    app = FastAPI()
    app.include_router(autonomy_routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return type("S", (), {"client": TestClient(app), "calls": calls, "app": app})()


def test_stand_down_calls_all_three(stand):
    got = stand.client.post("/autonomy/stand-down").json()
    assert got == {"beast_off": True, "swarm_off": True, "scheduler_paused": True, "failed": []}
    assert stand.calls == ["beast:False", "swarm:False", "pause:True"]


def test_stand_down_one_failure_does_not_stop_the_rest(stand, monkeypatch):
    async def broken(_state, enabled):
        raise OSError("config.json unwritable")

    monkeypatch.setattr(autonomy_routes.switch, "set_enabled", broken)
    got = stand.client.post("/autonomy/stand-down").json()
    assert got == {"beast_off": True, "swarm_off": False, "scheduler_paused": True, "failed": ["swarm_off"]}
    assert "pause:True" in stand.calls


def test_stand_down_requires_auth(stand):
    stand.app.dependency_overrides.clear()
    assert TestClient(stand.app).post("/autonomy/stand-down").status_code in (401, 403)


def test_autonomy_off_mcp_tool_is_registered_and_takes_no_arguments():
    import asyncio

    from src.core.mcp import tools
    from src.core.mcp.common import ToolError

    assert "autonomy_off" in tools._TOOLS
    handler = tools._TOOLS["autonomy_off"][3]
    with pytest.raises(ToolError):
        asyncio.run(handler(None, None, {"x": 1}))


def test_stand_down_all_failed_is_500_with_the_same_body(stand, monkeypatch):
    async def broken_async(*a, **kw):
        raise OSError("unwritable")

    def broken_sync(*a, **kw):
        raise OSError("unwritable")

    monkeypatch.setattr(autonomy_routes.beast_mode_routes, "set_beast_mode", broken_async)
    monkeypatch.setattr(autonomy_routes.switch, "set_enabled", broken_async)
    monkeypatch.setattr(autonomy_routes.pause, "set_paused", broken_sync)
    response = stand.client.post("/autonomy/stand-down")
    assert response.status_code == 500
    assert response.json() == {"beast_off": False, "swarm_off": False, "scheduler_paused": False,
                               "failed": ["beast_off", "swarm_off", "scheduler_paused"]}

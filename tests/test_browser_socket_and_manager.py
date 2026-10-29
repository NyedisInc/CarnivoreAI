
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_brw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_brw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.auth import require_auth
from src.api.browser_routes import router as rest_router
from src.api.browser_socket import router as ws_router
from src.config.browser import BrowserConfig
from src.core.browsers import store
from src.core.browsers.manager import BrowserManager, CapReached
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated

JWT_SECRET = "test-secret-for-ws-browser"
BID = "0123456789abcdef"


@pytest.fixture(autouse=True)
def patched_auth_config(monkeypatch):
    from src.config import settings as real_settings

    fake_auth = SimpleNamespace(
        jwt_secret=JWT_SECRET, jwt_expiry_minutes=60,
        access_token_ttl_seconds=900, refresh_token_ttl_seconds=604800,
        refresh_grace_seconds=10, totp_secret="X" * 32,
    )

    class _FakeSettings:
        def load_auth_config(self):
            return fake_auth

        def __getattr__(self, name):
            return getattr(real_settings, name)

    monkeypatch.setattr("src.api.auth.settings", _FakeSettings())


def _token() -> str:
    payload = {"exp": datetime.utcnow() + timedelta(minutes=60),
               "iat": datetime.utcnow(), "sub": "claudetunnel_user", "typ": "access"}
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


class FakeLive:

    def __init__(self, browser_id: str) -> None:
        self.id = browser_id
        self.viewers: set = set()
        self.idle_task = None
        self.stopping = False
        self.handled: list = []
        self.closed = False

    async def add_viewer(self, viewer) -> bool:
        self.viewers.add(viewer)
        self.viewer = viewer
        viewer.offer_text({"type": "meta", "width": 800, "height": 600, "dpr": 1})
        return True

    async def remove_viewer(self, viewer) -> None:
        self.viewers.discard(viewer)

    async def handle(self, msg, *, may_resize: bool) -> None:
        self.handled.append((msg.get("type"), may_resize))
        if msg.get("type") == "echo":
            self.viewer.offer_text({"type": "echo"})

    async def close(self) -> None:
        self.closed = True


class FakeManager(BrowserManager):

    def __init__(self, state_dir: Path, cfg: BrowserConfig) -> None:
        super().__init__(state_dir, lambda: cfg)
        self.left = 0

    async def _launch(self, browser_id, url):
        cfg = self._config()
        if len(self.live) >= cfg.max_live:
            raise CapReached(f"cap is {cfg.max_live}")
        live = FakeLive(browser_id)
        self.live[browser_id] = live
        return live

    async def _open_url(self, live, url) -> None:
        pass

    async def leave(self, live, viewer) -> None:
        await super().leave(live, viewer)
        self.left += 1


@pytest.fixture()
def env(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        with conn:
            store.insert(conn, BID, "example.com", "about:blank")
    manager = FakeManager(tmp_path, BrowserConfig(max_live=1, idle_stop_minutes=5))
    app = FastAPI()
    app.state.browser_manager = manager
    app.include_router(rest_router, prefix="/api/v1")
    app.include_router(ws_router)
    app.dependency_overrides[require_auth] = lambda: True
    return app, manager


def _wait(predicate, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_no_credential_is_refused_before_accept(env):
    app, manager = env
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect(f"/ws/browser?browser_id={BID}") as ws:
            ws.receive_text()
    assert exc.value.code == 4401
    assert manager.live == {}


def test_an_unknown_or_malformed_id_closes_4404(env):
    app, manager = env
    for bad in ("ffffffffffffffff", "../../etc", ""):
        with pytest.raises(WebSocketDisconnect) as exc:
            with TestClient(app).websocket_connect(
                    f"/ws/browser?browser_id={bad}",
                    subprotocols=["cloude.jwt.v1", _token()]) as ws:
                ws.receive_text()
        assert exc.value.code == 4404
    assert manager.live == {}


def _send_and_close(app, manager, query: str) -> list:
    with TestClient(app).websocket_connect(
            f"/ws/browser?browser_id={BID}{query}",
            subprotocols=["cloude.jwt.v1", _token()]) as ws:
        assert json.loads(ws.receive_text())["type"] == "restarted"
        assert json.loads(ws.receive_text())["type"] == "meta"
        ws.send_text(json.dumps({"type": "mouse", "event": "down", "x": 1, "y": 1,
                                 "button": "left", "clickCount": 1}))
        ws.send_text(json.dumps({"type": "resize", "width": 900, "height": 700}))
    assert _wait(lambda: manager.left >= 1)
    return manager.live[BID].handled


def test_an_observer_socket_input_is_ignored(env):
    app, manager = env
    assert _send_and_close(app, manager, "&observer=1") == []


def test_a_primary_socket_drives_and_an_interactive_observer_cannot_resize(env):
    app, manager = env
    assert _send_and_close(app, manager, "") == [("mouse", True), ("resize", True)]
    manager.live[BID].handled.clear()
    manager.left = 0
    handled = _send_and_close_live(app, manager, "&observer=1&interactive=1")
    assert handled == [("mouse", False), ("resize", False)]


def _send_and_close_live(app, manager, query: str) -> list:
    with TestClient(app).websocket_connect(
            f"/ws/browser?browser_id={BID}{query}",
            subprotocols=["cloude.jwt.v1", _token()]) as ws:
        assert json.loads(ws.receive_text())["type"] == "meta"
        ws.send_text(json.dumps({"type": "mouse", "event": "down", "x": 1, "y": 1,
                                 "button": "left", "clickCount": 1}))
        ws.send_text(json.dumps({"type": "resize", "width": 900, "height": 700}))
    assert _wait(lambda: manager.left >= 1)
    return manager.live[BID].handled


def test_an_input_flood_closes_4429(env):
    app, manager = env
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect(
                f"/ws/browser?browser_id={BID}",
                subprotocols=["cloude.jwt.v1", _token()]) as ws:
            for _ in range(600):
                ws.send_text("{}")
            ws.send_text(json.dumps({"type": "echo"}))
            while True:
                assert json.loads(ws.receive_text())["type"] != "echo"
    assert exc.value.code == 4429


def test_create_past_the_cap_is_refused_and_leaves_nothing(env):
    app, manager = env
    manager.live["aaaaaaaaaaaaaaaa"] = FakeLive("aaaaaaaaaaaaaaaa")
    client = TestClient(app)
    response = client.post("/api/v1/browsers", json={"url": "example.com"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "browser_cap_reached"
    assert [b["id"] for b in client.get("/api/v1/browsers").json()["browsers"]] == [BID]


def test_the_real_launch_refuses_past_the_cap_before_starting_anything(tmp_path):
    manager = BrowserManager(tmp_path, lambda: BrowserConfig(max_live=1))
    manager.live["aaaaaaaaaaaaaaaa"] = FakeLive("aaaaaaaaaaaaaaaa")
    with pytest.raises(CapReached, match="cap is 1"):
        asyncio.run(manager.launch(BID, "about:blank"))
    assert manager._pw is None
    assert not store.browsers_root(tmp_path).exists()


def test_create_with_a_refused_url_is_400(env):
    app, _ = env
    response = TestClient(app).post("/api/v1/browsers", json={"url": "file:///etc/passwd"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "browser_url_refused"


def test_a_browser_with_no_viewers_is_stopped_when_idle(tmp_path):

    async def scenario():
        manager = BrowserManager(tmp_path, lambda: BrowserConfig(idle_stop_minutes=0.002))
        watched, idle = FakeLive("aaaaaaaaaaaaaaaa"), FakeLive(BID)
        watched.viewers.add(object())
        for live in (watched, idle):
            manager.live[live.id] = live
            manager._arm_idle(live)
        await asyncio.sleep(0.5)
        return manager, watched, idle

    manager, watched, idle = asyncio.run(scenario())
    assert not manager.is_live(BID) and idle.closed
    assert manager.is_live("aaaaaaaaaaaaaaaa") and not watched.closed


def test_the_boot_sweep_kills_our_orphans_by_pid_and_drops_unowned_folders(tmp_path):
    import subprocess
    import sys

    from src.core.browsers.manager import sweep_orphans

    root = store.browsers_root(tmp_path)
    ours = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                             f"--user-data-dir={root}/{BID}/profile"])
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)",
                              f"--user-data-dir={tmp_path}/elsewhere/profile"])
    try:
        owned, orphan = store.make_profile_dir(tmp_path, BID), store.make_profile_dir(
            tmp_path, "fedcba9876543210")
        assert sweep_orphans(tmp_path, None)["folders_removed"] == 0
        assert orphan.exists() and ours.wait(timeout=10) == -9
        result = sweep_orphans(tmp_path, {BID})
        assert result["folders_removed"] == 1
        assert owned.exists() and not orphan.parent.exists()
        assert other.poll() is None, "a process outside our root was killed"
    finally:
        for proc in (ours, other):
            if proc.poll() is None:
                proc.kill()


def test_rename_navigate_and_close_a_stopped_browser(env):
    app, _ = env
    client = TestClient(app)
    renamed = client.patch(f"/api/v1/browsers/{BID}", json={"label": "docs"})
    assert renamed.status_code == 200 and renamed.json()["label"] == "docs"
    moved = client.post(f"/api/v1/browsers/{BID}/navigate",
                        json={"url": "example.com/cb?code=SECRET"})
    assert moved.status_code == 200
    assert moved.json()["url"] == "https://example.com/cb"
    assert moved.json()["state"] == "stopped"
    assert client.post(f"/api/v1/browsers/{BID}/navigate",
                       json={"url": "chrome://settings"}).status_code == 400
    assert client.patch("/api/v1/browsers/ffffffffffffffff",
                        json={"label": "x"}).status_code == 404
    assert client.delete(f"/api/v1/browsers/{BID}").status_code == 204
    assert client.get("/api/v1/browsers").json()["browsers"] == []
    assert client.delete(f"/api/v1/browsers/{BID}").status_code == 404

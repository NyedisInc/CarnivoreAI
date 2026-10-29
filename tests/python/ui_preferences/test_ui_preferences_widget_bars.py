
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wb_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wb_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from types import SimpleNamespace

from src.api import auth, widget_bars_routes
from src.api.auth import create_access_token
from src.api.preferences_routes import router as preferences_router
from src.api.widget_bars_routes import router as widget_bars_router
from src.core import ui_preferences
from src.core.federation import peer_token
from src.core.ui_preferences_store import UiPreferencesStore

FULL = {"v": 1, "side": {"show": False, "size": "compact", "mode": "pinned"},
        "bottom": {"show": True, "size": "detailed", "mode": "autohide"}, "together": "one"}
RAIL = {"v": 1, "items": [{"widget": "core.notes"}]}


class _Manager:

    def __init__(self) -> None:
        self.frames = []

    async def broadcast(self, text: str) -> None:
        self.frames.append(json.loads(text))


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {"a": 1}}))
    return path


def _app(config_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(preferences_router, prefix="/api/v1")
    app.include_router(widget_bars_router, prefix="/api/v1")
    app.state.ui_preferences_store = UiPreferencesStore(lambda: config_path)
    app.state.connection_manager = _Manager()
    return app


@pytest.fixture
def client(config_path: Path):
    app = _app(config_path)
    app.dependency_overrides[widget_bars_routes.require_auth] = lambda: True
    with TestClient(app) as test_client:
        test_client.app_state = app.state
        yield test_client


def _patch(client, changes):
    return client.patch("/api/v1/preferences", json={"changes": changes})


def test_a_full_and_a_sparse_value_round_trip_and_absent_stays_absent(client):
    assert "widget_bars" in ui_preferences.known_fields()
    assert "widget_bars" not in client.get("/api/v1/preferences").json()["values"]
    assert _patch(client, {"widget_bars": FULL}).json()["values"]["widget_bars"] == FULL
    sparse = {"v": 1, "side": {"size": "compact"}}
    assert _patch(client, {"widget_bars": sparse}).json()["values"]["widget_bars"] == sparse


@pytest.mark.parametrize(
    "bad",
    [
        {"v": 1, "side": {"size": "huge"}},
        {"v": 1, "bottom": {"show": 1}},
        {"v": 1, "side": {"mode": "float"}},
        {"v": 1, "together": "all"},
        {"v": 1, "side": {"show": True, "extra": 1}},
        {"v": 1, "extra": 1},
        {"v": 1, "rail": {"mode": "float"}},
        {"v": 1, "rail": {"mode": "pinned", "size": "compact"}},
        {"v": 1, "rail": "pinned"},
        {"v": 2},
        "compact",
    ],
)
def test_a_bad_value_is_refused_400(client, bad):
    assert _patch(client, {"widget_bars": bad}).status_code == 400


def test_the_sidebar_rail_leaf_round_trips_sparse_and_reset_clears_it(client):
    pinned = {"v": 1, "rail": {"mode": "pinned"}}
    assert _patch(client, {"widget_bars": pinned}).json()["values"]["widget_bars"] == pinned
    both = {"v": 1, "side": {"size": "compact"}, "rail": {"mode": "autohide"}}
    assert _patch(client, {"widget_bars": both}).json()["values"]["widget_bars"] == both
    assert client.post("/api/v1/preferences/widget-bars/reset").json()["status"] == "committed"
    assert "widget_bars" not in client.get("/api/v1/preferences").json()["values"]


def test_reset_clears_all_three_fields_in_one_revision_bump_and_one_broadcast(client):
    seeded = _patch(client, {"widget_bars": FULL, "session_rail": RAIL, "session_rail_bottom": RAIL}).json()
    frames = client.app_state.connection_manager.frames
    before = len(frames)
    answer = client.post("/api/v1/preferences/widget-bars/reset").json()
    assert answer["status"] == "committed"
    assert answer["revision"] == seeded["revision"] + 1
    for field in ("widget_bars", "session_rail", "session_rail_bottom"):
        assert field not in answer["values"]
    assert len(frames) == before + 1
    assert frames[-1]["revision"] == answer["revision"] and frames[-1]["origin_client_id"] is None


def test_reset_when_already_absent_is_unchanged_with_no_bump_and_no_broadcast(client):
    revision = client.get("/api/v1/preferences").json()["revision"]
    answer = client.post("/api/v1/preferences/widget-bars/reset").json()
    assert answer["status"] == "unchanged" and answer["revision"] == revision
    assert client.app_state.connection_manager.frames == []


def test_reset_refuses_a_peer_token_and_accepts_the_owner_token(config_path, monkeypatch):
    secret = "j" * 40
    monkeypatch.setattr(auth, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret=secret)))
    app = _app(config_path)
    with TestClient(app) as raw:
        url = "/api/v1/preferences/widget-bars/reset"
        assert raw.post(url).status_code == 401
        peer = jwt.encode({"typ": peer_token.PEER_TYP, "sub": "g1"}, secret, algorithm="HS256")
        assert peer_token.is_peer_token(peer)
        assert raw.post(url, headers={"Authorization": f"Bearer {peer}"}).status_code == 401
        owner, _ttl = create_access_token()
        assert raw.post(url, headers={"Authorization": f"Bearer {owner}"}).status_code == 200

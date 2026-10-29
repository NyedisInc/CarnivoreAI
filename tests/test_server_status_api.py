from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_statapi_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_statapi_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import status_routes
from src.api.auth import require_auth
from src.api.status_routes import router as status_router
from src.core.sessions.registry import SessionRegistry
from tests.socket_guard import shipped_default_socket_name


class FakeBackend:

    def __init__(self, tmux_session: str) -> None:
        self.tmux_session = tmux_session


class FakeSessionManager:

    def __init__(self, attachable=None, backends=None) -> None:
        self._attachable = attachable or []
        self._registry = SessionRegistry(log_cap=lambda: 1000)
        for sid, name in (backends or {}).items():
            self._registry.backends[sid] = FakeBackend(name)

    def list_attachable_sessions(self) -> list:
        return self._attachable


def _app(session_manager, authed: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(status_router, prefix="/api/v1")
    app.state.session_manager = session_manager
    if authed:
        app.dependency_overrides[require_auth] = lambda: True
    return app


@pytest.fixture()
def manager():
    return FakeSessionManager(
        attachable=[
            {"name": "cloude_ses_2a5a4495", "created_by_cloude": True},
            {"name": "someone-elses", "created_by_cloude": False},
        ],
        backends={"adopted:cloude_ses_2a5a4495": "cloude_ses_2a5a4495"},
    )



def test_status_without_a_token_is_401(manager):
    client = TestClient(_app(manager, authed=False))
    resp = client.get("/api/v1/server/status")
    assert resp.status_code == 401, resp.text


def test_status_with_a_junk_bearer_token_is_401(manager):
    client = TestClient(_app(manager, authed=False))
    resp = client.get(
        "/api/v1/server/status",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401, resp.text


def test_status_route_declares_the_auth_dependency():
    route = next(
        r for r in status_router.routes
        if getattr(r, "path", "") == "/server/status"
    )
    assert any(
        getattr(d, "dependency", None) is require_auth for d in route.dependencies
    ), "GET /server/status must depend on require_auth"



def test_status_returns_every_section(manager):
    client = TestClient(_app(manager))
    body = client.get("/api/v1/server/status").json()
    for section in ("server", "tmux", "claude_cli", "host", "memory",
                    "disk", "load"):
        assert section in body, section


def test_status_is_503_without_a_session_manager():
    app = FastAPI()
    app.include_router(status_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    resp = TestClient(app).get("/api/v1/server/status")
    assert resp.status_code == 503


def test_ownership_map_is_read_from_the_session_manager(manager):
    assert status_routes.ownership_by_name(manager) == {
        "cloude_ses_2a5a4495": True,
        "someone-elses": False,
    }


def test_ownership_survives_an_adopted_id_on_an_app_created_session(manager):
    ownership = status_routes.ownership_by_name(manager)
    open_ids = status_routes.open_ids_by_name(manager)
    assert open_ids == {"cloude_ses_2a5a4495": "adopted:cloude_ses_2a5a4495"}
    assert ownership["cloude_ses_2a5a4495"] is True


def test_ownership_map_is_empty_when_the_manager_cannot_answer():
    class Broken:
        _registry = SessionRegistry(log_cap=lambda: 1000)

        def list_attachable_sessions(self):
            raise RuntimeError("tmux exploded")

    assert status_routes.ownership_by_name(Broken()) == {}


def test_open_ids_is_empty_when_nothing_is_registered():
    class Nothing:
        _registry = SessionRegistry(log_cap=lambda: 1000)

    assert status_routes.open_ids_by_name(Nothing()) == {}


def test_socket_name_falls_back_when_config_is_unreadable(monkeypatch):
    class BadSettings:
        def load_auth_config(self):
            raise OSError("config gone")

    monkeypatch.setattr(status_routes, "settings", BadSettings())
    assert status_routes.resolve_socket_name() == status_routes.DEFAULT_SOCKET_NAME
    assert shipped_default_socket_name() == "carnivore"

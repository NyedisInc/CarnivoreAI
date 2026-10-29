
from __future__ import annotations

import subprocess
import time
import uuid

import pytest

from src.core.tmux_discovery import tmux_argv_prefix
from tests.socket_guard import TEST_SOCKET_NAME


class _Backend:
    def __init__(self, name):
        self.tmux_session = name


class _Registry:
    def __init__(self, backends):
        self.backends = backends
        self.sessions = dict.fromkeys(backends)
        self.get_backend = backends.get

    def is_hidden(self, _sid):
        return False

    def registered_ids_for_tmux_name(self, name):
        return [sid for sid, b in self.backends.items() if b.tmux_session == name]


class _Manager:
    def __init__(self, backends):
        self._registry = _Registry(backends)

    def tmux_socket_name(self):
        return TEST_SOCKET_NAME


def _client(backends):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = _Manager(backends)
    return TestClient(app)


def test_route_refuses_without_auth():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.session_manager = _Manager({})
    assert TestClient(app).post("/api/v1/warroom/screens", json={"items": []}).status_code in (401, 403, 503)


@pytest.mark.real_tmux
def test_screens_shape_dead_pane_and_unchanged_hash():
    name = f"cloude_wr_{uuid.uuid4().hex[:8]}"
    prefix = tmux_argv_prefix(TEST_SOCKET_NAME)
    subprocess.run(prefix + ["new-session", "-d", "-s", name, "-x", "70", "-y", "20",
                             "printf '\\033[31mRED\\033[0m plain'; sleep 30"], check=True)
    try:
        client = _client({"ses_1": _Backend(name), "ses_gone": _Backend("cloude_wr_missing")})
        for _ in range(40):
            first = client.post("/api/v1/warroom/screens", json={"items": [{"id": "ses_1"}]}).json()["screens"]["ses_1"]
            if "RED" in first["screen"]:
                break
            time.sleep(0.1)
        assert (first["status"], first["cols"], first["rows"]) == ("ok", 70, 20)
        assert "\x1b[31mRED" in first["screen"] and first["screen"].count("\r\n") == 19 and first["hash"]
        body = client.post("/api/v1/warroom/screens", json={"items": [
            {"id": "ses_1", "hash": first["hash"]}, {"id": "ses_gone"}, {"id": "nope"}, {"id": "remote:peer-x:a"}]})
        assert body.status_code == 200
        screens = body.json()["screens"]
        assert "ses_1" not in screens
        assert screens["ses_gone"]["status"] == "gone" and screens["nope"]["status"] == "gone"
        assert screens["remote:peer-x:a"]["status"] == "unsupported"
        again = client.post("/api/v1/warroom/screens", json={"items": [{"id": "ses_1", "hash": "stale"}]}).json()["screens"]
        assert again["ses_1"]["screen"] == first["screen"]
        assert client.post("/api/v1/warroom/screens", json={"items": [{"id": f"s{i}"} for i in range(41)]}).status_code == 422
    finally:
        subprocess.run(prefix + ["kill-session", "-t", f"={name}"], check=False)

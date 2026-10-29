
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import router
from src.core.session_manager import SessionManager
from src.models import SessionStatus


class _Trap:

    def has_active_session(self):
        raise AssertionError("health forked tmux via has_active_session")

    async def get_session_info(self, *a, **k):
        raise AssertionError("health built a SessionInfo")

    def _build_tmux_status_map(self):
        raise AssertionError("health ran list-panes")


class _Sess:
    def __init__(self, status, working_dir="/x/CloudeCode", age=90):
        self.status = status
        self.working_dir = working_dir
        self.created_at = datetime.utcnow() - timedelta(seconds=age)


class _Registry:
    def __init__(self, sess):
        self._sess = sess

    def current_session(self):
        return self._sess


class _Manager(_Trap):
    health_summary = SessionManager.health_summary

    def __init__(self, sess):
        self._registry = _Registry(sess)


def _client(manager) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.state.session_manager = manager
    app.state.local_servers = None
    return TestClient(app)


def test_health_reports_name_and_uptime_without_any_costly_call() -> None:
    body = _client(_Manager(_Sess(SessionStatus.RUNNING))).get("/api/v1/health").json()
    assert body["session_name"] == "CloudeCode"
    assert 89 <= body["uptime"] <= 95
    assert body["status"] == "running"


def test_health_with_no_running_session_keeps_the_old_empty_shape() -> None:
    body = _client(_Manager(None)).get("/api/v1/health").json()
    assert body["session_name"] is None
    assert body["uptime"] == 0

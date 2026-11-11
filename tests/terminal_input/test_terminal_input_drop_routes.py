
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_drops_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_drops_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

# ruff: noqa: E402
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import terminal_input_drop_routes as routes
from src.api.auth import require_auth

REPORT = {
    "reason": "owner_refused", "slot": "@primary", "owner": "terminal:row:32",
    "active_slot": "terminal:row:32", "hidden": False, "ws_state": 1,
    "buffer_phase": "ready", "page_ms": 123456,
}


@pytest.fixture()
def client():
    routes._last_logged.clear()
    routes._recent.clear()
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def test_refused_write_logs_exactly_one_rate_limited_event(client):
    with structlog.testing.capture_logs() as logs:
        first = client.post("/terminal/input-drops", json=REPORT)
        again = client.post("/terminal/input-drops", json=REPORT)
        other_reason = client.post("/terminal/input-drops", json={**REPORT, "reason": "no_socket"})
    assert first.status_code == 202 and first.json() == {"logged": True}
    assert again.json() == {"logged": False}
    assert other_reason.json() == {"logged": True}
    events = [e for e in logs if e["event"] == "terminal_input_dropped"]
    assert len(events) == 2, "the repeat inside 10 s must not log"
    got = events[0]
    for k, v in REPORT.items():
        assert got[k] == v
    assert set(got) <= {"event", "log_level", "layout_id", *REPORT}
    assert not any(k in got for k in ("key", "keyCode", "data", "text", "bytes"))


def test_rejects_unknown_fields_and_prose(client):
    assert client.post("/terminal/input-drops", json={**REPORT, "key": "a"}).status_code == 422
    assert client.post("/terminal/input-drops", json={**REPORT, "slot": "hunter2 is my password"}).status_code == 422
    assert client.post("/terminal/input-drops", json={**REPORT, "reason": "bogus"}).status_code == 422


def test_global_limit_stops_a_flood(client):
    with structlog.testing.capture_logs() as logs:
        for i in range(routes.GLOBAL_PER_MINUTE + 20):
            client.post("/terminal/input-drops", json={**REPORT, "slot": f"s{i}"})
    assert len([e for e in logs if e["event"] == "terminal_input_dropped"]) == routes.GLOBAL_PER_MINUTE


def test_requires_auth():
    app = FastAPI()
    app.include_router(routes.router)
    assert TestClient(app).post("/terminal/input-drops", json=REPORT).status_code == 401

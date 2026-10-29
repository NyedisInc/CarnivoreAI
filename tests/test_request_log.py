from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
import structlog
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api import request_log  # noqa: E402
from src.api.request_log import LOG_EXTRA_KEY, RequestLogMiddleware  # noqa: E402


@pytest.fixture(autouse=True)
def _permissive_structlog_level():
    original = structlog.get_config()["wrapper_class"]
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))
    yield
    structlog.configure(wrapper_class=original)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLogMiddleware)

    @app.get("/api/thing")
    async def ok_route(request: Request):
        return {"ok": True}

    @app.post("/api/thing")
    async def write_route():
        return {"ok": True}

    @app.post("/mcp")
    async def mcp_route(request: Request):
        request.scope[LOG_EXTRA_KEY] = {"rpc": (await request.body()).decode()}
        return {"ok": True}

    @app.get("/boom")
    async def boom_route():
        raise RuntimeError("handler blew up")

    @app.get("/api/v1/server-log")
    async def server_log_route():
        return {"entries": []}

    @app.get("/static/app.js")
    async def static_route():
        return {"asset": True}

    @app.websocket("/ws")
    async def ws_route(websocket: WebSocket):
        await websocket.accept()
        text = await websocket.receive_text()
        await websocket.send_text(f"echo:{text}")
        await websocket.close()

    return app


def _client() -> TestClient:
    return TestClient(_build_app())


def _only_http_request_events(logs: list[dict]) -> list[dict]:
    return [e for e in logs if e.get("event") == "http_request"]


def test_successful_request_logs_all_five_fields():
    client = _client()
    with structlog.testing.capture_logs() as logs:
        resp = client.post("/api/thing")
    assert resp.status_code == 200

    events = _only_http_request_events(logs)
    assert len(events) == 1
    entry = events[0]
    assert entry["method"] == "POST"
    assert entry["path"] == "/api/thing"
    assert entry["status"] == 200
    assert entry["client_ip"] == "testclient"
    assert isinstance(entry["duration_ms"], (int, float))
    assert entry["duration_ms"] >= 0
    assert entry["log_level"] == "info"


def test_raised_handler_logs_status_500_and_still_raises():
    client = _client()
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(RuntimeError, match="handler blew up"):
            client.get("/boom")

    events = _only_http_request_events(logs)
    assert len(events) == 1
    assert events[0]["status"] == 500
    assert events[0]["path"] == "/boom"


def test_query_string_never_appears_in_the_logged_path_or_anywhere_else():
    client = _client()
    with structlog.testing.capture_logs() as logs:
        resp = client.post("/api/thing?token=abc123secret")
    assert resp.status_code == 200

    events = _only_http_request_events(logs)
    assert len(events) == 1
    assert events[0]["path"] == "/api/thing"
    assert "?" not in events[0]["path"]

    serialized = repr(logs)
    assert "abc123secret" not in serialized


def test_websocket_route_is_not_logged_and_still_works():
    client = _client()
    with structlog.testing.capture_logs() as logs:
        with client.websocket_connect("/ws") as ws:
            ws.send_text("hello")
            reply = ws.receive_text()

    assert reply == "echo:hello"
    assert _only_http_request_events(logs) == []


def test_static_path_logs_at_debug_level():
    client = _client()
    with structlog.testing.capture_logs() as logs:
        resp = client.get("/static/app.js")
    assert resp.status_code == 200

    events = _only_http_request_events(logs)
    assert len(events) == 1
    assert events[0]["log_level"] == "debug"


def test_api_path_logs_at_info_level():
    client = _client()
    with structlog.testing.capture_logs() as logs:
        client.post("/api/thing")

    events = _only_http_request_events(logs)
    assert len(events) == 1
    assert events[0]["log_level"] == "info"


def test_server_log_reads_log_at_debug_so_the_viewer_does_not_fill_itself():
    client = _client()
    with structlog.testing.capture_logs() as logs:
        assert client.get("/api/v1/server-log").status_code == 200
        assert client.post("/api/thing").status_code == 200

    by_path = {e["path"]: e["log_level"] for e in _only_http_request_events(logs)}
    assert by_path["/api/v1/server-log"] == "debug"
    assert by_path["/api/thing"] == "info"


def test_routine_reads_and_pings_are_rolled_up_but_errors_and_writes_keep_their_line():
    request_log._ROLLUP.reset()
    client = _client()
    with structlog.testing.capture_logs() as logs:
        assert client.get("/api/thing").status_code == 200
        assert client.get("/api/thing").status_code == 200
        assert client.post("/mcp", content="ping").status_code == 200
        assert client.post("/mcp", content="tools/call").status_code == 200
        assert client.post("/api/thing").status_code == 200
        with pytest.raises(RuntimeError):
            client.get("/boom")
        request_log.flush_rollup()

    per_request = {(e["method"], e["path"], e.get("rpc"), e["status"]) for e in _only_http_request_events(logs)}
    assert per_request == {("POST", "/mcp", "tools/call", 200), ("POST", "/api/thing", None, 200), ("GET", "/boom", None, 500)}
    (rollup,) = [e for e in logs if e.get("event") == "http_request_rollup"]
    rows = {(r["method"], r["path"], r["rpc"]): r for r in rollup["routes"]}
    assert rows[("GET", "/api/thing", "")]["count"] == 2
    assert rows[("POST", "/mcp", "ping")]["count"] == 1
    assert rollup["requests"] == 3
    assert {"total_ms", "avg_ms", "max_ms"} <= rows[("GET", "/api/thing", "")].keys()

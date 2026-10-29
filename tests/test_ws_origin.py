
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from src.api.host_guard import UNTRUSTED_CLOSE_CODE, HostGuardMiddleware, HostPolicy
from tests.test_ws_subprotocol_auth import (  # noqa: F401
    _mint_token,
    patched_auth_config,
    ws_app,
)

HOST = "198.51.100.18:8000"
PATHS = ["/ws/terminal", "/ws/events"]


@pytest.mark.parametrize("origin,host", [
    (None, HOST),
    ("http://198.51.100.18:8000", HOST),
    ("https://198.51.100.18:8000", HOST),
    ("HTTP://198.51.100.18:8000/", HOST),
    ("http://[::1]:8000", "[::1]:8000"),
    ("https://hosta.example.net", "hosta.example.net"),
    ("http://hosta.example.net", "hosta.example.net"),
    ("https://tunnel.example.com", "127.0.0.1:8000"),
    ("https://box.tailnet.ts.net", "127.0.0.1:8000"),
])
def test_origin_trusted(origin, host):
    policy = HostPolicy("*.tailnet.ts.net", ["https://tunnel.example.com"])
    assert policy.origin_trusted(origin, host) is True


@pytest.mark.parametrize("origin,host", [
    ("http://evil.example", HOST),
    ("null", HOST),
    ("http://198.51.100.18:9999", HOST),
    ("http://198.51.100.18", HOST),
    ("ftp://198.51.100.18:8000", HOST),
    ("http://198.51.100.18:bad", HOST),
    ("", HOST),
    ("http://127.0.0.1:8000", None),
    ("https://tunnel.example.com.evil.example", "127.0.0.1:8000"),
])
def test_origin_refused(origin, host):
    policy = HostPolicy("*.tailnet.ts.net", ["https://tunnel.example.com"])
    assert policy.origin_trusted(origin, host) is False




def _close_code(app, path: str, headers: dict, subprotocols=None) -> int:
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect(path, headers=headers, subprotocols=subprotocols) as ws:
            ws.receive_text()
    return exc.value.code


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("origin", ["http://evil.example", "null", "http://198.51.100.18:9999"])
def test_real_app_refuses_foreign_origin(path, origin):
    from src.main import app
    with capture_logs() as logs:
        code = _close_code(app, path, {"host": HOST, "origin": origin})
    assert code == UNTRUSTED_CLOSE_CODE
    assert any(e["event"] == "websocket_origin_rejected" and e["origin"] == origin for e in logs)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("origin", [None, "http://198.51.100.18:8000"])
def test_real_app_trusted_origin_reaches_auth(path, origin):
    from src.main import app
    headers = {"host": HOST} if origin is None else {"host": HOST, "origin": origin}
    assert _close_code(app, path, headers) == 4401


def test_empty_subprotocol_still_4400_with_trusted_origin():
    from src.main import app
    headers = {"host": HOST, "origin": "http://198.51.100.18:8000", "sec-websocket-protocol": " "}
    assert _close_code(app, "/ws/terminal", headers) == 4400




def _events_app() -> FastAPI:
    from src.api.events_routes import router as events_router
    from src.core.event_hub import EventHub
    app = FastAPI()
    app.state.event_hub = EventHub()
    app.include_router(events_router)
    return app


@pytest.fixture(params=PATHS)
def guarded(request, ws_app):
    path = request.param
    app = ws_app if path == "/ws/terminal" else _events_app()
    app.add_middleware(HostGuardMiddleware)
    return app, path


def _auth():
    return ["cloude.jwt.v1", _mint_token()]


def test_valid_jwt_foreign_origin_refused(guarded):
    app, path = guarded
    code = _close_code(app, path, {"host": HOST, "origin": "http://evil.example"}, _auth())
    assert code == UNTRUSTED_CLOSE_CODE


@pytest.mark.parametrize("origin", [None, "http://198.51.100.18:8000", "https://198.51.100.18:8000"])
def test_valid_jwt_trusted_origin_accepted(guarded, origin):
    app, path = guarded
    headers = {"host": HOST} if origin is None else {"host": HOST, "origin": origin}
    with TestClient(app).websocket_connect(path, headers=headers, subprotocols=_auth()) as ws:
        assert ws.accepted_subprotocol == "cloude.jwt.v1"
        first = {"/ws/terminal": "request_dims", "/ws/events": "events.hello"}[path]
        assert ws.receive_json()["type"] == first

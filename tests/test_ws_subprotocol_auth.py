from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import jwt as pyjwt
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


JWT_SECRET = "test-secret-for-ws-subproto-auth"


@pytest.fixture(autouse=True)
def patched_auth_config(monkeypatch):
    from src.config import settings as real_settings
    import src.api.auth as auth_mod

    fake_auth = SimpleNamespace(
        jwt_secret=JWT_SECRET,
        jwt_expiry_minutes=60,
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=604800,
        refresh_grace_seconds=10,
        totp_secret="X" * 32,
    )

    class _FakeSettings:

        def load_auth_config(self):
            return fake_auth

        def __getattr__(self, name):
            return getattr(real_settings, name)

    fake_settings = _FakeSettings()

    monkeypatch.setattr("src.api.auth.settings", fake_settings)
    yield


def _mint_token(expiry_minutes: int = 60) -> str:
    payload = {
        "exp": datetime.utcnow() + timedelta(minutes=expiry_minutes),
        "iat": datetime.utcnow(),
        "sub": "claudetunnel_user",
        "typ": "access",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _mint_expired_token() -> str:
    payload = {
        "exp": datetime.utcnow() - timedelta(minutes=5),
        "iat": datetime.utcnow() - timedelta(minutes=65),
        "sub": "claudetunnel_user",
        "typ": "access",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _fake_ws(header_value):
    headers = {}
    if header_value is not None:
        headers["sec-websocket-protocol"] = header_value
    ws = MagicMock()
    ws.headers.get.side_effect = lambda k, default=None: headers.get(k.lower(), default)
    return ws



def test_valid_subprotocol_and_token_returns_true():
    from src.api.deps import verify_jwt_from_subprotocol

    token = _mint_token()
    ws = _fake_ws(f"cloude.jwt.v1, {token}")

    ok, payload = verify_jwt_from_subprotocol(ws)

    assert ok is True
    assert payload == token


def test_valid_subprotocol_order_reversed_returns_true():
    from src.api.deps import verify_jwt_from_subprotocol

    token = _mint_token()
    ws = _fake_ws(f"{token}, cloude.jwt.v1")

    ok, payload = verify_jwt_from_subprotocol(ws)

    assert ok is True
    assert payload == token


def test_missing_marker_returns_false_missing_subprotocol():
    from src.api.deps import verify_jwt_from_subprotocol

    token = _mint_token()
    ws = _fake_ws(f"{token}")

    ok, reason = verify_jwt_from_subprotocol(ws)

    assert ok is False
    assert reason == "missing subprotocol"


def test_marker_without_token_returns_false_missing_token():
    from src.api.deps import verify_jwt_from_subprotocol

    ws = _fake_ws("cloude.jwt.v1")

    ok, reason = verify_jwt_from_subprotocol(ws)

    assert ok is False
    assert reason == "missing token"


def test_invalid_jwt_returns_false_invalid_token():
    from src.api.deps import verify_jwt_from_subprotocol

    ws = _fake_ws("cloude.jwt.v1, this.is.not-a-valid-jwt")

    ok, reason = verify_jwt_from_subprotocol(ws)

    assert ok is False
    assert reason == "invalid token"


def test_expired_jwt_returns_false_invalid_token():
    from src.api.deps import verify_jwt_from_subprotocol

    token = _mint_expired_token()
    ws = _fake_ws(f"cloude.jwt.v1, {token}")

    ok, reason = verify_jwt_from_subprotocol(ws)

    assert ok is False
    assert reason == "invalid token"


def test_empty_header_returns_false_missing_subprotocol():
    from src.api.deps import verify_jwt_from_subprotocol

    ws = _fake_ws("")

    ok, reason = verify_jwt_from_subprotocol(ws)

    assert ok is False
    assert reason == "missing subprotocol"


def test_no_header_at_all_returns_false_missing_subprotocol():
    from src.api.deps import verify_jwt_from_subprotocol

    ws = _fake_ws(None)

    ok, reason = verify_jwt_from_subprotocol(ws)

    assert ok is False
    assert reason == "missing subprotocol"


def test_whitespace_only_header_returns_false_missing_subprotocol():
    from src.api.deps import verify_jwt_from_subprotocol

    ws = _fake_ws("   ,  ,   ")

    ok, reason = verify_jwt_from_subprotocol(ws)

    assert ok is False
    assert reason == "missing subprotocol"


def test_token_signed_with_wrong_secret_rejected():
    from src.api.deps import verify_jwt_from_subprotocol

    payload = {
        "exp": datetime.utcnow() + timedelta(minutes=10),
        "iat": datetime.utcnow(),
        "sub": "claudetunnel_user",
    }
    bad_token = pyjwt.encode(payload, "a-totally-different-secret", algorithm="HS256")
    ws = _fake_ws(f"cloude.jwt.v1, {bad_token}")

    ok, reason = verify_jwt_from_subprotocol(ws)

    assert ok is False
    assert reason == "invalid token"




class _FakeQueue:
    async def get(self):
        import asyncio
        await asyncio.Future()


class _FakeSessionManager:

    def capture_scrollback(self, lines=3000, session_id=None):
        return b""

    async def send_input(self, text, session_id=None):
        pass

    def resize_terminal(self, cols, rows, session_id=None):
        pass


class _FakeLocalServers:

    def subscribe(self):
        return _FakeQueue()

    def unsubscribe(self, q):
        pass


class _FakeLogMonitor:
    def subscribe(self):
        return _FakeQueue()

    def unsubscribe(self, q):
        pass

    def _detect_patterns(self, text):
        pass


@pytest.fixture
def ws_app():
    from fastapi import FastAPI
    from src.api.websocket import router as ws_router

    from types import SimpleNamespace

    from src.core.sessions.registry import SessionRegistry

    app = FastAPI()
    app.state.session_manager = _FakeSessionManager()
    app.state.services = SimpleNamespace(
        registry=SessionRegistry(log_cap=lambda: 1000)
    )
    app.state.local_servers = _FakeLocalServers()
    app.state.log_monitor = _FakeLogMonitor()
    app.include_router(ws_router)
    return app


def test_ws_connect_with_valid_subprotocol_accepted(ws_app):
    from fastapi.testclient import TestClient

    client = TestClient(ws_app)
    token = _mint_token()

    with client.websocket_connect(
        "/ws/terminal",
        subprotocols=["cloude.jwt.v1", token],
    ) as ws:
        assert ws.accepted_subprotocol == "cloude.jwt.v1"
        first = ws.receive_json()
        assert first.get("type") == "request_dims"


def test_ws_connect_without_subprotocol_rejected_4401(ws_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(ws_app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/terminal") as ws:
            ws.receive_text()

    assert exc_info.value.code == 4401


def test_ws_connect_with_invalid_token_rejected_4401(ws_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(ws_app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/terminal",
            subprotocols=["cloude.jwt.v1", "not-a-real-jwt"],
        ) as ws:
            ws.receive_text()

    assert exc_info.value.code == 4401


def test_ws_connect_marker_only_no_token_rejected_4401(ws_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(ws_app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/terminal",
            subprotocols=["cloude.jwt.v1"],
        ) as ws:
            ws.receive_text()

    assert exc_info.value.code == 4401


def test_ws_connect_expired_token_rejected_4401(ws_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(ws_app)
    token = _mint_expired_token()

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/terminal",
            subprotocols=["cloude.jwt.v1", token],
        ) as ws:
            ws.receive_text()

    assert exc_info.value.code == 4401


def test_ws_connect_with_malformed_subprotocol_rejected_4400(ws_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(ws_app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/terminal",
            subprotocols=[""],
        ) as ws:
            ws.receive_text()

    assert exc_info.value.code == 4400


def test_ws_connect_with_unknown_session_id_rejected_4404(ws_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(ws_app)
    token = _mint_token()

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/terminal?session_id=some-ephemeral-id-the-server-forgot",
            subprotocols=["cloude.jwt.v1", token],
        ) as ws:
            ws.receive_text()

    assert exc_info.value.code == 4404


def test_ws_connect_with_old_query_token_no_longer_works(ws_app):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(ws_app)
    token = _mint_token()

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/ws/terminal?token={token}") as ws:
            ws.receive_text()

    assert exc_info.value.code == 4401

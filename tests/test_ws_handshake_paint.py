from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.test_ws_subprotocol_auth import (  # noqa: F401
    _mint_token,
    patched_auth_config,
)

PAINT_MARKER = b"CLOUDE-HANDSHAKE-PAINT-MARKER"

SESSION_ID = "ses_paint_probe"
TMUX_NAME = "cloude_paint_probe"

SENTINEL_DELAY_SECONDS = 2.5
SENTINEL_TYPE = "cloude.test.handshake-window-closed"


class _PaintableBackend:

    def __init__(self) -> None:
        self.tmux_session = TMUX_NAME

    def pane_in_alternate_screen(self) -> bool:
        return False

    def capture_visible_screen(self) -> bytes:
        return PAINT_MARKER

    def session_age_seconds(self) -> float:
        return 1.0


class _ParkedQueue:

    async def get(self):
        import asyncio

        await asyncio.Future()


class _SentinelQueue:

    def __init__(self, delay: float) -> None:
        self._delay = delay
        self._sent = False

    async def get(self) -> str:
        import asyncio

        if self._sent:
            await asyncio.Future()
        self._sent = True
        await asyncio.sleep(self._delay)
        return json.dumps({"type": SENTINEL_TYPE})


class _NoBackendLookupManager:

    def capture_scrollback(self, lines=3000, session_id=None) -> bytes:
        return b""

    async def send_input(self, text, session_id=None) -> None:
        pass

    def resize_terminal(self, cols, rows, session_id=None) -> None:
        pass


class _FakeLocalServers:

    def subscribe(self):
        return _ParkedQueue()

    def unsubscribe(self, q) -> None:
        pass


class _FakeLogMonitor:

    def subscribe(self):
        return _SentinelQueue(SENTINEL_DELAY_SECONDS)

    def unsubscribe(self, q) -> None:
        pass

    def _detect_patterns(self, text) -> None:
        pass


@pytest.fixture
def paint_app():
    from fastapi import FastAPI

    from src.api.websocket import router as ws_router
    from src.core.sessions.registry import SessionRegistry
    from src.models import Session

    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(
        Session(id=SESSION_ID, working_dir="/tmp"),
        _PaintableBackend(),
    )

    app = FastAPI()
    app.state.session_manager = _NoBackendLookupManager()
    app.state.services = SimpleNamespace(registry=registry)
    app.state.local_servers = _FakeLocalServers()
    app.state.log_monitor = _FakeLogMonitor()
    app.include_router(ws_router)
    return app


def _drive_handshake(ws, cols: int = 100, rows: int = 30):
    from src.models import WSMessageType

    answered = False
    while True:
        message = ws.receive()

        if message.get("bytes"):
            return message["bytes"]

        text = message.get("text")
        if not text:
            if message.get("type") == "websocket.close":
                return None
            continue

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue

        if parsed.get("type") == SENTINEL_TYPE:
            return None

        if not answered and parsed.get("type") == WSMessageType.REQUEST_DIMS:
            ws.send_text(json.dumps({
                "type": WSMessageType.PTY_RESIZE,
                "cols": cols,
                "rows": rows,
            }))
            answered = True


def test_a_completed_handshake_paints_the_pane_to_the_client(paint_app):
    from fastapi.testclient import TestClient

    client = TestClient(paint_app)
    token = _mint_token()

    with client.websocket_connect(
        f"/ws/terminal?session_id={SESSION_ID}",
        subprotocols=["cloude.jwt.v1", token],
    ) as ws:
        painted = _drive_handshake(ws)

    assert painted is not None, (
        "the attach never painted: the handshake window closed without a "
        "single binary frame. This is the 1.4.0 defect - the geometry read "
        "was handed an object with no `get_backend`, the AttributeError was "
        "swallowed, and the resize and the paint were both skipped while "
        "the socket stayed up and streaming"
    )
    assert PAINT_MARKER in painted, (
        "a binary frame arrived but did not carry the pane's screen; the "
        f"attach painted something else: {painted!r}"
    )


def test_the_handshake_does_not_swallow_an_error_on_the_way(paint_app, caplog):
    from fastapi.testclient import TestClient

    client = TestClient(paint_app)
    token = _mint_token()

    with caplog.at_level("ERROR"):
        with client.websocket_connect(
            f"/ws/terminal?session_id={SESSION_ID}",
            subprotocols=["cloude.jwt.v1", token],
        ) as ws:
            painted = _drive_handshake(ws)

    assert painted is not None and PAINT_MARKER in painted
    assert "ws_handshake_error" not in caplog.text, (
        "the handshake raised and was swallowed; the paint above may be "
        f"masking a real failure:\n{caplog.text}"
    )


def test_the_two_collaborators_are_not_interchangeable():
    from src.core.session_manager import SessionManager
    from src.core.sessions.registry import SessionRegistry

    for member in ("get_backend", "current_backend"):
        assert hasattr(SessionRegistry, member), (
            f"SessionRegistry lost {member}; _resolve_backend's contract "
            "moved and this suite is now measuring the wrong pairing"
        )
        assert not hasattr(SessionManager, member), (
            f"SessionManager grew {member}. That is not automatically "
            "wrong, but it makes the wrong-object defect silent again, so "
            "the paint tests above no longer prove which object was passed"
        )

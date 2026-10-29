
from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_specws_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_specws_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from tests.test_ws_subprotocol_auth import (  # noqa: F401
    _mint_token,
    patched_auth_config,
)
from tests.test_ws_handshake_paint import (
    _FakeLocalServers,
    _FakeLogMonitor,
    _PaintableBackend,
)

from src.core.spectator_links_store import SpectatorLinksStore

SESSION_ID = "ses_spectator_probe"

LIVE_MARKER = b"CLOUDE-SPECTATOR-STILL-STREAMING"

OLD_SPECTATOR_MARKER = "cloude.spectator.v1"


class _RecordingManager:

    def __init__(self) -> None:
        self.viewed: list[str] = []
        self.inputs: list[str] = []

    def mark_session_viewed(self, session_id: str) -> None:
        self.viewed.append(session_id)

    async def send_input(self, text, session_id=None) -> None:
        self.inputs.append(text)

    def resize_terminal(self, cols, rows, session_id=None) -> None:
        pass

    def capture_scrollback(self, lines=3000, session_id=None) -> bytes:
        return b""


class _PassThroughRedactor:

    stats = SimpleNamespace(chunks_in=0, findings=0, detectors=())

    def feed(self, chunk: str) -> str:
        return chunk

    def flush(self) -> str:
        return ""


class _SocketRegistry:

    def register(self, link_id, websocket, expires_at):
        return (link_id, websocket, expires_at)

    def release(self, entry) -> None:
        pass

    async def close_link(self, link_id) -> int:
        return 0


def _build_app(store: SpectatorLinksStore):
    from fastapi import FastAPI

    from src.api.websocket import router as ws_router
    from src.core.sessions.registry import SessionRegistry
    from src.models import Session

    @asynccontextmanager
    async def lifespan(app):
        await store.init()
        app.state.spectator_links = store
        yield
        await store.close()

    registry = SessionRegistry(log_cap=lambda: 1000)
    registry.register(Session(id=SESSION_ID, working_dir="/tmp"), _PaintableBackend())

    app = FastAPI(lifespan=lifespan)
    app.state.spectator_redactor_factory = _PassThroughRedactor
    app.state.spectator_sockets = _SocketRegistry()
    app.state.session_manager = _RecordingManager()
    app.state.services = SimpleNamespace(registry=registry)
    app.state.local_servers = _FakeLocalServers()
    app.state.log_monitor = _FakeLogMonitor()
    app.include_router(ws_router)
    return app


@pytest.fixture
def store(tmp_path):
    return SpectatorLinksStore(str(tmp_path / "cloude.db"))


@pytest.fixture
def app(store):
    return _build_app(store)


def test_a_live_shares_token_opens_no_socket_on_this_install(app, store):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as client:
        minted = client.portal.call(lambda: store.mint(SESSION_ID, 600, None))
        assert minted.link.is_live(), "the control share is not live"
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect(
                f"/ws/terminal?session_id={SESSION_ID}",
                subprotocols=[OLD_SPECTATOR_MARKER, minted.token],
            ) as ws:
                ws.receive()

    assert refused.value.code == 4401, (
        f"a share token was not refused on the local socket: {refused.value.code}"
    )
    assert app.state.session_manager.viewed == [], (
        "a refused share token still marked the session viewed"
    )


def test_a_spectator_token_cannot_pass_require_auth(app, store):
    import asyncio

    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth

    def _present(raw: str):
        return asyncio.run(require_auth(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw)
        ))

    with TestClient(app) as client:
        minted = client.portal.call(lambda: store.mint(SESSION_ID, 600, None))

    with pytest.raises(HTTPException) as refused:
        _present(minted.token)
    assert refused.value.status_code == 401, (
        "A SHARE TOKEN AUTHENTICATED AS THE OWNER."
    )
    assert _present(_mint_token()) is True, (
        "no token passes require_auth here, so the refusal above proves nothing"
    )


def test_the_apps_own_jwt_socket_still_connects_on_the_same_app(app, store):
    from fastapi.testclient import TestClient

    from src.models import WSMessageType

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/terminal?session_id={SESSION_ID}",
            subprotocols=["cloude.jwt.v1", _mint_token()],
        ) as ws:
            asked = False
            for _ in range(10):
                text = ws.receive().get("text")
                if text and json.loads(text).get("type") == WSMessageType.REQUEST_DIMS:
                    asked = True
                    break
            assert asked, "the app's own socket was not asked for its dims"
            ws.send_text(json.dumps({"type": "pty_resize", "cols": 100, "rows": 30}))
            ws.send_bytes(b"echo hello\r")
            app.state.services.registry.publish(SESSION_ID, LIVE_MARKER)
            for _ in range(40):
                if LIVE_MARKER in (ws.receive().get("bytes") or b""):
                    break

    assert app.state.session_manager.inputs == ["echo hello\r"], (
        f"the app's own terminal stopped being able to type: "
        f"{app.state.session_manager.inputs!r}"
    )

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from src.core.sessions.registry import SessionRegistry
from fastapi.testclient import TestClient
from PIL import Image

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_upload_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_upload_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api.routes import router as api_router  # noqa: E402
from src.core.session_manager import SessionManager  # noqa: E402
from src.core.upload_sweeper import UPLOAD_DIR_NAME  # noqa: E402
from src.models import Session, SessionStatus  # noqa: E402


JWT_SECRET = "test-secret-for-upload-image"
MAX_SIZE_MB = 10
MAX_FILE_SIZE_MB = 50


def _make_fake_auth_config():
    uploads = SimpleNamespace(
        enabled=True,
        ttl_seconds=86400,
        sweep_interval_seconds=3600,
        max_size_mb=MAX_SIZE_MB,
        max_file_size_mb=MAX_FILE_SIZE_MB,
    )
    return SimpleNamespace(
        jwt_secret=JWT_SECRET,
        jwt_expiry_minutes=30,
        access_token_ttl_seconds=900,
        refresh_token_ttl_seconds=604800,
        refresh_grace_seconds=10,
        totp_secret="X" * 32,
        uploads=uploads,
    )


@pytest.fixture(autouse=True)
def patched_auth(monkeypatch):
    fake = _make_fake_auth_config()
    from src.config import settings as real_settings

    def fake_loader(self=None):
        return fake

    monkeypatch.setattr(type(real_settings), "load_auth_config", fake_loader)
    return fake


def _mint_access_token() -> str:
    payload = {
        "exp": datetime.utcnow() + timedelta(minutes=15),
        "iat": datetime.utcnow(),
        "sub": "claudetunnel_user",
        "typ": "access",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _png_bytes(size: tuple[int, int] = (10, 10), color: str = "red") -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(buf, format="JPEG")
    return buf.getvalue()


def _webp_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (10, 10), "green").save(buf, format="WEBP")
    return buf.getvalue()


class _StubSessionManager:

    def __init__(self, working_dir: Path | None):
        self._wd = working_dir
        self.registry = SessionRegistry(log_cap=lambda: 1000)
        if working_dir is not None:
            backend = MagicMock()
            backend.is_alive.return_value = True
            self.registry.register(
                Session(
                    id="ses_test01",
                    working_dir=str(working_dir),
                    status=SessionStatus.RUNNING,
                ),
                backend,
            )

    def has_active_session(self) -> bool:
        session = self.registry.current_session()
        backend = self.registry.current_backend()
        return (
            session is not None
            and session.status == SessionStatus.RUNNING
            and backend is not None
            and backend.is_alive()
        )


def _app_with(manager: _StubSessionManager) -> FastAPI:
    app = FastAPI()
    app.state.session_manager = manager
    app.state.services = SimpleNamespace(registry=manager.registry)
    app.include_router(api_router, prefix="/api/v1")
    return app


@pytest.fixture
def app_with_session(tmp_path):
    return _app_with(_StubSessionManager(tmp_path))


@pytest.fixture
def app_without_session():
    return _app_with(_StubSessionManager(None))


@pytest.fixture
def client(app_with_session):
    return TestClient(app_with_session)


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {_mint_access_token()}"}


def test_upload_requires_auth(client):
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    r = client.post("/api/v1/sessions/upload-image", files=files)
    assert r.status_code == 401, r.text


def test_upload_valid_png_writes_to_session_dir(client, auth_headers, tmp_path):
    data = _png_bytes()
    files = {"file": ("test.png", data, "image/png")}
    r = client.post("/api/v1/sessions/upload-image", files=files, headers=auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()

    target = Path(body["path"])
    assert target.exists(), f"upload not on disk: {target}"
    assert target.parent == (tmp_path / UPLOAD_DIR_NAME).resolve()
    assert target.suffix == ".png"
    assert body["filename"] == target.name
    assert body["size"] == len(data)
    assert target.read_bytes() == data


def test_upload_valid_jpeg_writes_to_session_dir(client, auth_headers, tmp_path):
    data = _jpeg_bytes()
    files = {"file": ("photo.jpg", data, "image/jpeg")}
    r = client.post("/api/v1/sessions/upload-image", files=files, headers=auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    target = Path(body["path"])
    assert target.exists()
    assert target.suffix == ".jpg"
    assert target.parent == (tmp_path / UPLOAD_DIR_NAME).resolve()
    assert body["size"] == len(data)


def test_upload_valid_webp_accepted(client, auth_headers, tmp_path):
    data = _webp_bytes()
    files = {"file": ("clip.webp", data, "image/webp")}
    r = client.post("/api/v1/sessions/upload-image", files=files, headers=auth_headers)
    assert r.status_code == 201, r.text
    target = Path(r.json()["path"])
    assert target.exists()
    assert target.suffix == ".webp"


def test_upload_non_image_extension_now_accepted(client, auth_headers, tmp_path):
    files = {"file": ("notes.txt", b"not an image", "text/plain")}
    r = client.post("/api/v1/sessions/upload-image", files=files, headers=auth_headers)
    assert r.status_code == 201, r.text
    target = Path(r.json()["path"])
    assert target.exists()
    assert target.suffix == ".txt"
    assert target.name.endswith("-notes.txt")
    assert target.read_bytes() == b"not an image"


def test_upload_image_extension_still_magic_checked(client, auth_headers):
    files = {"file": ("fake.png", b"definitely not a png", "image/png")}
    r = client.post("/api/v1/sessions/upload-image", files=files, headers=auth_headers)
    assert r.status_code == 400, r.text


def test_upload_magic_byte_mismatch_rejected(client, auth_headers):
    jpeg_bytes = _jpeg_bytes()
    files = {"file": ("fake.png", jpeg_bytes, "image/png")}
    r = client.post("/api/v1/sessions/upload-image", files=files, headers=auth_headers)
    assert r.status_code == 400, r.text
    detail = r.json()["detail"].lower()
    assert "match" in detail or "jpeg" in detail


def test_upload_oversized_rejected(client, auth_headers):
    oversized = b"\x89PNG\r\n\x1a\n" + b"A" * (MAX_SIZE_MB * 1024 * 1024 + 1)
    files = {"file": ("big.png", oversized, "image/png")}
    r = client.post("/api/v1/sessions/upload-image", files=files, headers=auth_headers)
    assert r.status_code == 400, r.text
    assert "size" in r.json()["detail"].lower() or "maximum" in r.json()["detail"].lower()


def test_upload_no_active_session_rejected(app_without_session, auth_headers):
    client = TestClient(app_without_session)
    files = {"file": ("test.png", _png_bytes(), "image/png")}
    r = client.post("/api/v1/sessions/upload-image", files=files, headers=auth_headers)
    assert r.status_code == 409, r.text
    assert "session" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_destroy_session_cleans_uploads_dir(tmp_path, monkeypatch):
    import src.core.session_manager as sm_mod

    metadata_path = tmp_path / "session_metadata.json"
    object.__setattr__(
        sm_mod.settings,
        "get_session_metadata_path",
        lambda: metadata_path,
    )

    uploads_dir = tmp_path / UPLOAD_DIR_NAME
    uploads_dir.mkdir(mode=0o700)
    (uploads_dir / "foo.png").write_bytes(b"fake-png-bytes")
    assert uploads_dir.exists()

    manager = SessionManager()
    backend = MagicMock()

    async def _stop():
        return None

    backend.stop = _stop
    backend.is_alive = MagicMock(return_value=True)
    backend.tmux_session = "cloude_destroy01"
    manager._registry.register(
        Session(
            id="ses_destroy01",
            working_dir=str(tmp_path),
            status=SessionStatus.RUNNING,
        ),
        backend,
    )

    await manager.destroy_session()

    assert not uploads_dir.exists(), "uploads dir must be removed on destroy"
    assert manager._registry.current_session() is None
    assert manager._registry.sessions == {}

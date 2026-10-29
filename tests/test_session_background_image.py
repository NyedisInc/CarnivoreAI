
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Set
from urllib.parse import quote

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_bgimg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_bgimg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import session_background_image_routes as image_routes
from src.api.auth import require_auth
from src.api.routes import router as api_router
from src.config import settings
from src.core.sessions.background_store import SessionBackgroundStore

SESSION = "cloude_bgimg"

SAMPLES = {
    "png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
    "jpg": b"\xff\xd8\xff\xe0" + b"\x00" * 64,
    "gif": b"GIF89a" + b"\x00" * 64,
    "webp": b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64,
    "avif": b"\x00\x00\x00\x20ftypavif" + b"\x00" * 64,
}

EXPECTED_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "avif": "image/avif",
}


class _FakeOwned:

    def __init__(self, names: Set[str]) -> None:
        self.names = names


class _FakeSessionManager:

    def __init__(self, names: Set[str]) -> None:
        self._names = names

    def active_tmux_names(self) -> Set[str]:
        return set(self._names)

    def list_attachable_sessions(self):
        return []


def _map_path(root: Path) -> Path:
    return root / "session_backgrounds.json"


def _images_dir(root: Path) -> Path:
    return root / "session_backgrounds"


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        image_routes, "_images_dir", lambda: _images_dir(tmp_path)
    )
    return tmp_path


def _build_app(root: Path, names: Set[str]) -> TestClient:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True

    app.state.session_background_store = SessionBackgroundStore(
        path=lambda: _map_path(root)
    )
    app.state.session_manager = _FakeSessionManager(names)

    class _Services:
        owned_tmux = _FakeOwned(names)

    app.state.services = _Services()
    return TestClient(app)


@pytest.fixture()
def client(state_dir):
    return _build_app(state_dir, {SESSION})


@pytest.fixture()
def one_megabyte_cap(tmp_path, monkeypatch):
    path = tmp_path / "cap-config.json"
    path.write_text(json.dumps({"uploads": {"max_size_mb": 1}}))
    monkeypatch.setattr(settings, "auth_config_file", str(path))
    settings._auth_config_cache = None
    assert settings.load_auth_config().uploads.max_size_mb == 1
    yield
    settings._auth_config_cache = None


def _put(client: TestClient, data: bytes, name: str = "picture.png",
         content_type: str = "image/png"):
    return client.put(
        f"/api/v1/sessions/{SESSION}/background/image",
        files={"file": (name, data, content_type)},
    )




@pytest.mark.parametrize("ext", sorted(SAMPLES))
def test_every_sniffed_format_is_accepted(client, state_dir, ext) -> None:
    resp = _put(client, SAMPLES[ext], name="whatever.bin",
                content_type="application/octet-stream")
    assert resp.status_code == 200, resp.text
    assert resp.json()["image"] == f"{SESSION}.{ext}"
    assert (_images_dir(state_dir) / f"{SESSION}.{ext}").is_file()


def test_a_text_file_called_png_is_refused(client, state_dir) -> None:
    resp = _put(client, b"this is not a picture at all\n" * 8,
                name="real.png", content_type="image/png")
    assert resp.status_code == 415
    assert not _images_dir(state_dir).exists()


def test_svg_is_refused(client, state_dir) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>'
    resp = _put(client, svg, name="pic.svg", content_type="image/svg+xml")
    assert resp.status_code == 415
    assert not _images_dir(state_dir).exists()


def test_an_empty_body_is_refused(client) -> None:
    assert _put(client, b"").status_code == 415




def test_over_the_cap_is_refused_without_writing(
    client, state_dir, one_megabyte_cap
) -> None:
    oversize = SAMPLES["png"] + b"\x00" * (2 * 1024 * 1024)
    resp = _put(client, oversize)
    assert resp.status_code == 413
    assert not _images_dir(state_dir).exists()


def test_at_the_cap_is_accepted(client, state_dir, one_megabyte_cap) -> None:
    exact = SAMPLES["png"] + b"\x00" * (1024 * 1024 - len(SAMPLES["png"]))
    assert len(exact) == 1024 * 1024
    assert _put(client, exact).status_code == 200
    assert (_images_dir(state_dir) / f"{SESSION}.png").is_file()




def test_an_unknown_session_is_refused(client, state_dir) -> None:
    resp = client.put(
        "/api/v1/sessions/not_a_session/background/image",
        files={"file": ("x.png", SAMPLES["png"], "image/png")},
    )
    assert resp.status_code == 404
    assert not _images_dir(state_dir).exists()


@pytest.mark.parametrize(
    "hostile",
    ["../../etc/passwd", "name with spaces", ".hidden", "na\\me"],
)
def test_a_session_name_that_cannot_be_a_filename_is_refused(
    state_dir, hostile
) -> None:
    local = _build_app(state_dir, {hostile})
    resp = local.put(
        f"/api/v1/sessions/{quote(hostile, safe='')}/background/image",
        files={"file": ("x.png", SAMPLES["png"], "image/png")},
    )
    assert resp.status_code in (400, 404), resp.text
    assert not _images_dir(state_dir).exists()




@pytest.mark.parametrize("ext", sorted(SAMPLES))
def test_the_get_serves_the_sniffed_type(client, ext) -> None:
    assert _put(client, SAMPLES[ext], name="x.png",
                content_type="image/png").status_code == 200
    resp = client.get(f"/api/v1/sessions/{SESSION}/background/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == EXPECTED_TYPES[ext]
    assert resp.content == SAMPLES[ext]


def test_the_get_is_not_cached(client) -> None:
    _put(client, SAMPLES["png"])
    resp = client.get(f"/api/v1/sessions/{SESSION}/background/image")
    assert "no-cache" in resp.headers.get("cache-control", "")


def test_the_get_is_404_with_nothing_stored(client) -> None:
    resp = client.get(f"/api/v1/sessions/{SESSION}/background/image")
    assert resp.status_code == 404




def test_a_reupload_of_another_type_leaves_no_old_file(client, state_dir) -> None:
    _put(client, SAMPLES["png"])
    assert (_images_dir(state_dir) / f"{SESSION}.png").is_file()

    resp = _put(client, SAMPLES["jpg"])
    assert resp.status_code == 200
    assert resp.json()["image"] == f"{SESSION}.jpg"
    assert (_images_dir(state_dir) / f"{SESSION}.jpg").is_file()
    assert not (_images_dir(state_dir) / f"{SESSION}.png").exists()


def test_delete_clears_the_file_and_the_field(client, state_dir) -> None:
    _put(client, SAMPLES["png"])
    resp = client.delete(f"/api/v1/sessions/{SESSION}/background/image")
    assert resp.status_code == 204
    assert not (_images_dir(state_dir) / f"{SESSION}.png").exists()

    listing = client.get("/api/v1/session-backgrounds").json()
    assert SESSION not in listing["overrides"]


def test_delete_is_idempotent(client) -> None:
    assert client.delete(
        f"/api/v1/sessions/{SESSION}/background/image"
    ).status_code == 204
    assert client.delete(
        f"/api/v1/sessions/{SESSION}/background/image"
    ).status_code == 204


def test_delete_keeps_the_other_three_fields(client) -> None:
    _put(client, SAMPLES["png"])
    patched = client.patch(
        f"/api/v1/sessions/{SESSION}/background",
        json={"theme_id": None, "dim": 0.95, "disabled": False},
    )
    assert patched.status_code == 200
    assert patched.json()["image"] == f"{SESSION}.png"

    client.delete(f"/api/v1/sessions/{SESSION}/background/image")
    entry = client.get("/api/v1/session-backgrounds").json()["overrides"][SESSION]
    assert entry["image"] is None
    assert entry["dim"] == 0.95


def test_the_upload_survives_a_reload_of_the_store(client, state_dir) -> None:
    _put(client, SAMPLES["png"])
    reloaded = SessionBackgroundStore(path=lambda: _map_path(state_dir))
    reloaded.load()
    assert reloaded.get(SESSION)["image"] == f"{SESSION}.png"


def test_a_hand_edited_unsafe_name_is_dropped_on_load(state_dir) -> None:
    _map_path(state_dir).write_text(
        json.dumps({SESSION: {"dim": 0.9, "image": "../../etc/passwd"}})
    )
    store = SessionBackgroundStore(path=lambda: _map_path(state_dir))
    store.load()
    entry = store.get(SESSION)
    assert entry is not None
    assert entry["image"] is None
    assert entry["dim"] == 0.9

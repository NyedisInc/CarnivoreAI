
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import notification_types_routes as routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.notify_media import store  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
BASE = "/api/v1/notifications/media/"


def _client(authed: bool, tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(store, "media_dir", lambda: tmp_path)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: None
    return TestClient(app)


def test_owner_reads_bytes_and_poster_with_the_safe_headers(tmp_path, monkeypatch) -> None:
    c = _client(True, tmp_path, monkeypatch)
    saved = store.write("video", b"movie-bytes", "video/mp4", poster=PNG)
    r = c.get(BASE + saved.media_id)
    assert r.status_code == 200 and r.content == b"movie-bytes" and r.headers["content-type"] == "video/mp4"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"].startswith("attachment")
    p = c.get(BASE + saved.media_id + "/poster")
    assert p.status_code == 200 and p.content == PNG and p.headers["content-type"] == "image/png"


def test_unknown_bad_and_posterless_ids_are_404(tmp_path, monkeypatch) -> None:
    c = _client(True, tmp_path, monkeypatch)
    saved = store.write("image", PNG, "image/png")
    assert c.get(BASE + "0" * 32).status_code == 404
    assert c.get(BASE + "..%2f..%2fetc%2fpasswd").status_code == 404
    assert c.get(BASE + saved.media_id + "/poster").status_code == 404


def test_login_is_required(tmp_path, monkeypatch) -> None:
    c = _client(False, tmp_path, monkeypatch)
    saved = store.write("image", PNG, "image/png")
    assert c.get(BASE + saved.media_id).status_code in (401, 403)

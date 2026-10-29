
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_mgrrm_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_mgrrm_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import theme_export_routes, themes_routes
from src.api.auth import require_auth


def _app(authed: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(theme_export_routes.router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return app


@pytest.fixture()
def client():
    with TestClient(_app()) as c:
        yield c



def _theme(root: Path, tid: str, **extra) -> Path:
    d = root / tid
    d.mkdir(parents=True)
    (d / "theme.json").write_text(json.dumps({"id": tid, "name": tid, "description": "d", **extra}))
    return d


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    bundled, user = tmp_path / "bundled", tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    monkeypatch.setattr(themes_routes, "_bundled_themes_root", lambda: bundled)
    monkeypatch.setattr(themes_routes, "_user_themes_root", lambda: user)
    return bundled, user


def test_export_serves_the_theme_json_as_a_download(client, roots):
    bundled, user = roots
    _theme(bundled, "dusk", cssVars={"--color-bg": "#000"})
    _theme(user, "mine")
    resp = client.get("/api/v1/themes/dusk/export")
    assert resp.status_code == 200
    assert 'filename="dusk.theme.json"' in resp.headers["content-disposition"]
    assert resp.json() == {"id": "dusk", "name": "dusk", "description": "d", "cssVars": {"--color-bg": "#000"}}
    assert client.get("/api/v1/themes/mine/export").json()["id"] == "mine"


def test_the_real_bundled_themes_export():
    with TestClient(_app()) as c:
        resp = c.get("/api/v1/themes/dracula/export")
    assert resp.status_code == 200
    on_disk = json.loads((ROOT / "client/css/themes/dracula/theme.json").read_text())
    assert resp.json() == on_disk


def test_bundled_wins_an_id_collision(client, roots):
    bundled, user = roots
    _theme(bundled, "same", name="bundled one")
    _theme(user, "same", name="user one")
    assert client.get("/api/v1/themes/same/export").json()["name"] == "bundled one"


def test_export_refuses_no_credential(roots):
    _theme(roots[0], "dusk")
    with TestClient(_app(authed=False)) as c:
        assert c.get("/api/v1/themes/dusk/export").status_code == 401


@pytest.mark.parametrize("tid", ["..", ".hidden", "a.b", "_shared", "%2e%2e", "x" * 129])
def test_export_refuses_ids_that_are_not_names(client, roots, tid):
    resp = client.get(f"/api/v1/themes/{tid}/export")
    assert resp.status_code in (400, 404)


def test_an_encoded_traversal_cannot_reach_a_file_outside(client, roots, tmp_path):
    (tmp_path / "theme.json").write_text(json.dumps({"id": "..", "secret": True}))
    resp = client.get("/api/v1/themes/..%2F..%2F/export")
    assert resp.status_code in (400, 404)
    assert "secret" not in resp.text


def test_export_refuses_a_symlinked_theme_dir_or_file(client, roots, tmp_path):
    bundled, user = roots
    elsewhere = _theme(tmp_path / "elsewhere", "linked")
    (user / "linked").symlink_to(elsewhere, target_is_directory=True)
    resp = client.get("/api/v1/themes/linked/export")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "symlink"
    d = user / "filelink"
    d.mkdir()
    (d / "theme.json").symlink_to(elsewhere / "theme.json")
    resp = client.get("/api/v1/themes/filelink/export")
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "symlink"


def test_export_refuses_a_file_naming_another_theme(client, roots):
    d = roots[1] / "liar"
    d.mkdir()
    (d / "theme.json").write_text(json.dumps({"id": "dracula"}))
    resp = client.get("/api/v1/themes/liar/export")
    assert resp.status_code == 422 and resp.json()["detail"]["code"] == "not_a_manifest"


def test_export_refuses_an_oversize_file(client, roots, monkeypatch):
    _theme(roots[0], "big", pad="x" * 400)
    monkeypatch.setattr(theme_export_routes, "MAX_THEME_JSON_BYTES", 100)
    resp = client.get("/api/v1/themes/big/export")
    assert resp.status_code == 413 and resp.json()["detail"]["code"] == "too_large"


def test_unknown_theme_is_404(client, roots):
    resp = client.get("/api/v1/themes/nope/export")
    assert resp.status_code == 404 and resp.json()["detail"]["code"] == "not_found"

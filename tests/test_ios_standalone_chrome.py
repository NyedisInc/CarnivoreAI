
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ios_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ios_logs_"))
os.environ.setdefault("CLOUDE_STATE_DIR", tempfile.mkdtemp(prefix="cc_ios_state_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from src.main import app

    with TestClient(app) as tc:
        yield tc


@pytest.fixture(scope="module")
def shell(client):
    resp = client.get("/")
    assert resp.status_code == 200
    return resp.text


class TestServedMetaTags:
    def test_viewport_opts_into_cover(self, shell):
        assert "viewport-fit=cover" in shell

    def test_web_app_capable(self, shell):
        assert 'name="apple-mobile-web-app-capable" content="yes"' in shell
        assert 'name="mobile-web-app-capable" content="yes"' in shell

    def test_status_bar_style(self, shell):
        assert 'name="apple-mobile-web-app-status-bar-style"' in shell
        assert 'content="black-translucent"' in shell

    def test_home_screen_title(self, shell):
        assert 'name="apple-mobile-web-app-title"' in shell

    def test_theme_color(self, shell):
        assert 'name="theme-color"' in shell

    def test_manifest_link_points_at_the_origin_root(self, shell):
        assert 'rel="manifest" href="/manifest.webmanifest"' in shell

    def test_apple_touch_icon_is_a_png(self, shell):
        assert 'rel="apple-touch-icon"' in shell
        line = [ln for ln in shell.splitlines() if 'rel="apple-touch-icon"' in ln][0]
        assert ".png" in line


class TestManifestRoute:
    def test_served_from_root(self, client):
        resp = client.get("/manifest.webmanifest")
        assert resp.status_code == 200

    def test_media_type_is_the_one_chrome_accepts(self, client):
        resp = client.get("/manifest.webmanifest")
        assert resp.headers["content-type"].startswith("application/manifest+json")

    def test_is_valid_json_with_the_required_keys(self, client):
        data = json.loads(client.get("/manifest.webmanifest").text)
        for key in ("name", "short_name", "start_url", "scope", "display", "icons"):
            assert key in data, f"manifest missing {key}"

    def test_display_is_standalone(self, client):
        data = json.loads(client.get("/manifest.webmanifest").text)
        assert data["display"] == "standalone"

    def test_scope_is_the_origin_root(self, client):
        data = json.loads(client.get("/manifest.webmanifest").text)
        assert data["scope"] == "/"
        assert data["start_url"] == "/"

    def test_declares_a_maskable_icon(self, client):
        data = json.loads(client.get("/manifest.webmanifest").text)
        purposes = {i.get("purpose") for i in data["icons"]}
        assert "maskable" in purposes

    def test_every_declared_icon_actually_resolves(self, client):
        data = json.loads(client.get("/manifest.webmanifest").text)
        for icon in data["icons"]:
            resp = client.get(icon["src"])
            assert resp.status_code == 200, f"{icon['src']} -> {resp.status_code}"
            assert resp.headers["content-type"] == "image/png"


class TestAppleTouchIconRoute:
    def test_root_probe_answers(self, client):
        resp = client.get("/apple-touch-icon.png")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    def test_linked_icon_resolves(self, client):
        resp = client.get("/static/assets/icons/icon-180.png")
        assert resp.status_code == 200

    def test_icon_is_the_size_it_claims(self):
        from PIL import Image
        path = ROOT / "client" / "assets" / "icons" / "icon-180.png"
        with Image.open(path) as img:
            assert img.size == (180, 180)


class TestSafeAreaCss:

    @pytest.fixture(scope="class")
    def css(self, client):
        resp = client.get("/static/css/ios-chrome.css")
        assert resp.status_code == 200
        return resp.text

    def test_header_pads_the_top_inset(self, css):
        assert "env(safe-area-inset-top)" in css

    def test_all_four_insets_are_handled(self, css):
        for side in ("top", "bottom", "left", "right"):
            assert f"env(safe-area-inset-{side})" in css

    def test_no_floating_control_is_left_to_inset(self, css):
        import re
        rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        assert "env(safe-area-inset-bottom)" in rules
        assert ".fab-menu-btn" not in rules


class TestNoServiceWorker:

    def test_shell_does_not_register_a_service_worker(self, shell):
        assert "serviceWorker" not in shell

    def test_no_service_worker_file_shipped(self):
        client_dir = ROOT / "client"
        found = [
            p.name for p in client_dir.rglob("*.js")
            if p.name in ("sw.js", "service-worker.js", "serviceworker.js")
        ]
        assert found == ["sw.js"], f"unexpected service worker: {found}"
        worker = (client_dir / "sw.js").read_text(encoding="utf-8")
        assert "'fetch'" not in worker and '"fetch"' not in worker, "sw.js must stay push-only"
        assert "caches." not in worker, "sw.js must not cache"

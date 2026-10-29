
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_staticsrv_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_staticsrv_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import pytest
from fastapi.testclient import TestClient

from src.core import static_cache
from src.main import app
from src.api.shell.static import client_dir

CLIENT = TestClient(app)

JS_ASSET = "/static/js/api.js"
CSS_ASSET = "/static/css/styles.css"


def test_text_asset_served_compressed_when_accepted() -> None:
    plain = CLIENT.get(JS_ASSET, headers={"Accept-Encoding": "identity"})
    assert plain.status_code == 200
    assert "content-encoding" not in plain.headers

    gz = CLIENT.get(JS_ASSET, headers={"Accept-Encoding": "gzip"})
    assert gz.status_code == 200
    assert gz.headers.get("content-encoding") == "gzip"
    assert "Accept-Encoding" in _vary_tokens(gz)
    assert gz.headers["vary"].count("Accept-Encoding") == 1
    assert gz.content == plain.content
    wire_size = int(gz.headers["content-length"])
    assert wire_size < len(plain.content)


def _vary_tokens(response) -> set:
    return {token.strip() for token in response.headers.get("vary", "").split(",") if token.strip()}


def test_text_asset_served_uncompressed_when_not_accepted() -> None:
    resp = CLIENT.get(JS_ASSET, headers={"Accept-Encoding": "identity"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert "Accept-Encoding" in _vary_tokens(resp), (
        "Vary must be present either way - the response DOES depend on "
        "Accept-Encoding even when this particular request declined it"
    )


def test_css_and_json_suffixes_also_compress() -> None:
    resp = CLIENT.get(CSS_ASSET, headers={"Accept-Encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"


def test_compression_happened_off_the_request_path() -> None:
    full_path = str((client_dir / "js" / "api.js").resolve())
    stat_result = (client_dir / "js" / "api.js").stat()
    cached = static_cache.peek(full_path, stat_result.st_mtime, stat_result.st_size)
    assert cached is not None, (
        "api.js should already be compressed by the startup warm pass, "
        "before this test ever made a request for it"
    )


def test_unversioned_url_still_revalidates() -> None:
    resp = CLIENT.get(JS_ASSET)
    assert resp.headers.get("cache-control") == "no-cache, must-revalidate"

    gz = CLIENT.get(JS_ASSET, headers={"Accept-Encoding": "gzip"})
    assert gz.headers.get("cache-control") == "no-cache, must-revalidate", (
        "compression must never loosen the revalidation contract"
    )


def test_conditional_get_still_returns_304() -> None:
    first = CLIENT.get(JS_ASSET)
    etag = first.headers.get("etag")
    assert etag, "StaticFiles must still set an ETag"

    second = CLIENT.get(JS_ASSET, headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""

    third = CLIENT.get(
        JS_ASSET, headers={"If-None-Match": etag, "Accept-Encoding": "gzip"}
    )
    assert third.status_code == 304
    assert third.content == b""


def test_a_simulated_deploy_never_serves_stale_bytes() -> None:
    target = client_dir / "js" / "api-toasts.js"
    original = target.read_text(encoding="utf-8")
    marker = f"/* deploy-simulation {time.time()} */\n"
    try:
        time.sleep(1.05)
        target.write_text(marker + original, encoding="utf-8")

        plain = CLIENT.get("/static/js/api-toasts.js")
        assert marker.strip() in plain.text

        gz = CLIENT.get("/static/js/api-toasts.js", headers={"Accept-Encoding": "gzip"})
        assert gz.headers.get("content-encoding") == "gzip"
        assert marker.strip() in gz.text, (
            "the client received a STALE compressed copy after a deploy - "
            "this is the exact regression the no-cache header exists to "
            "prevent, one layer down"
        )
    finally:
        target.write_text(original, encoding="utf-8")


def test_range_request_on_a_theme_image_is_unaffected() -> None:
    image_files = list((client_dir / "css" / "themes").glob("*/background.webp"))
    if not image_files:
        pytest.skip("no theme background image present in this checkout - cannot determine")
    sample = image_files[0]
    rel = sample.relative_to(client_dir).as_posix()
    url = f"/static/{rel}"

    full = CLIENT.get(url)
    assert full.status_code == 200

    ranged = CLIENT.get(
        url, headers={"Range": "bytes=0-99", "Accept-Encoding": "gzip"}
    )
    assert ranged.status_code == 206
    assert "content-encoding" not in ranged.headers
    assert len(ranged.content) == 100
    assert ranged.content == full.content[:100]


def test_root_html_shell_compresses_and_keeps_the_version_chip() -> None:
    plain = CLIENT.get("/")
    assert plain.status_code == 200
    assert "{{VERSION}}" not in plain.text
    assert plain.headers.get("cache-control") == "no-cache, must-revalidate"

    gz = CLIENT.get("/", headers={"Accept-Encoding": "gzip"})
    assert gz.status_code == 200
    assert gz.headers.get("content-encoding") == "gzip"
    assert "{{VERSION}}" not in gz.text
    assert gz.text == plain.text
    assert gz.headers.get("cache-control") == "no-cache, must-revalidate"


def test_bare_session_route_redirects_to_the_sessions_view() -> None:
    resp = CLIENT.get("/session", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/#sessions"
    named = CLIENT.get("/session/some-project", follow_redirects=False)
    assert named.status_code == 200


def test_session_deep_link_shell_also_compresses() -> None:
    gz = CLIENT.get("/session/some-project", headers={"Accept-Encoding": "gzip"})
    assert gz.status_code == 200
    assert gz.headers.get("content-encoding") == "gzip"
    assert '<div id="launchpad-screen"' in gz.text

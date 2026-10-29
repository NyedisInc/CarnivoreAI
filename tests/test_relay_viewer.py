
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from websockets.sync.client import connect

from relay import viewer
from relay.app import create_app
from relay.protocol import PUBLISH_SUBPROTOCOL
from tests.relay_support import RecordingFactory, data_frame, links_frame
from tests.test_relay_frame_limit import real_relay
from tests.test_relay_sockets import PUBLISH_TOKEN, build_settings

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARE_TOKEN = "relay-viewer-share-token-0123456789abcdef"


@pytest.fixture
def client():
    app = create_app(build_settings(), redactor_factory=RecordingFactory())
    with TestClient(app) as entered:
        yield entered


def test_the_page_is_served_with_the_strict_headers(client):
    response = client.get("/s/3f2a9c_link-ID", headers={"host": "relay.test"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    csp = {
        part.strip().split(" ", 1)[0]: part.strip().split(" ", 1)[1]
        for part in response.headers["content-security-policy"].split(";")
    }
    assert csp["default-src"] == "'self'"
    assert csp["script-src"] == "'self'"
    assert csp["connect-src"] == "'self' wss://relay.test"
    assert csp["frame-ancestors"] == "'none'"
    assert csp["object-src"] == "'none'"
    policy = response.headers["content-security-policy"]
    assert "unsafe-eval" not in policy and "http" not in policy and "*" not in policy
    assert 'id="spectate-screen"' in response.text


def test_a_host_header_that_is_not_a_plain_host_is_never_named_in_the_csp(client):
    response = client.get("/s/abc", headers={"host": "x; script-src https://evil.test"})
    assert response.status_code == 200
    assert "evil" not in response.headers["content-security-policy"]
    assert "connect-src 'self';" in response.headers["content-security-policy"]


def test_the_page_has_no_inline_script_and_names_only_allowlisted_assets(client):
    page = client.get("/s/abc").text
    assert not re.search(r"<script(?![^>]*\bsrc=)", page), "inline script"
    assert not re.search(r"\son[a-z]+=", page), "inline event handler"
    refs = re.findall(r'(?:src|href)="([^"]+)"', page)
    assert refs, "the page names no assets at all"
    for ref in refs:
        assert ref.startswith(viewer.ASSET_PREFIX), ref
        assert ref[len(viewer.ASSET_PREFIX):] in viewer.ASSETS, ref
        served = client.get(ref)
        assert served.status_code == 200, ref
        assert served.headers["x-content-type-options"] == "nosniff"
        expected = "text/css" if ref.endswith(".css") else "text/javascript"
        assert served.headers["content-type"].startswith(expected), ref
    assert viewer.missing_assets() == []


def test_the_wordmark_the_page_bar_names_is_served_same_origin(client):
    page_source = (REPO_ROOT / "web/src/spectate/SpectatePage.svelte").read_text()
    dockerfile = (REPO_ROOT / "relay/Dockerfile").read_text()
    for name in ("carnivore-wordmark.png", "carnivore-wordmark@2x.png"):
        ref = f"/static/img/carnivore/{name}"
        assert ref in page_source, ref
        served = client.get(ref)
        assert served.status_code == 200, ref
        assert served.headers["content-type"] == "image/png"
        assert served.headers["x-content-type-options"] == "nosniff"
        assert served.content == (REPO_ROOT / "client/img/carnivore" / name).read_bytes()
        assert f"client/img/carnivore/{name}" in dockerfile, name


@pytest.mark.parametrize(
    "path",
    [
        "/static/%2e%2e/relay/auth.py",
        "/static/dist/%2e%2e/%2e%2e/relay/auth.py",
        "/static/..%2f..%2frelay%2fauth.py",
        "/static/dist/../../relay/config.py",
        "/static/",
        "/static/dist/",
        "/static/dist",
        "/static/vendor/xterm/xterm-addon-webgl.js",
        "/static/dist/app.js.map",
        "/relay/auth.py",
        "/client/dist/app.js",
        "/s/",
        "/s/a/b",
        "/s/..%2fx",
        "/s/a.b",
        "/s/" + "x" * 129,
        "/spectate",
        "/",
    ],
)
def test_traversal_and_unknown_paths_are_404(client, path):
    response = client.get(path)
    assert response.status_code == 404, (path, response.status_code)
    assert "RELAY_PUBLISH_TOKEN" not in response.text


def test_the_page_code_takes_the_token_only_from_the_fragment_into_the_subprotocol():
    source = (REPO_ROOT / "web/src/spectate/spectate-socket.ts").read_text()
    url_builder = source[source.index("export function spectateSocketUrl"):]
    url_builder = url_builder[: url_builder.index("\n}\n")]
    assert "token" not in url_builder
    assert "hash" not in url_builder
    construct = re.search(
        r"new win\.WebSocket\(spectateSocketUrl\(win\.location\), \[\s*"
        r"RELAY_WATCH_SUBPROTOCOL,\s*token,\s*\]\)",
        source,
    )
    assert construct, "the socket is not opened with the token as the subprotocol"
    assert source.count("token") and "?token" not in source and "&token" not in source


def _publisher(port: int):
    return connect(
        f"ws://127.0.0.1:{port}/publish",
        additional_headers={"Authorization": f"Bearer {PUBLISH_TOKEN}"},
        subprotocols=[PUBLISH_SUBPROTOCOL],
    )


def test_in_a_real_browser_the_page_streams_and_never_sends_the_token():
    sync_api = pytest.importorskip(
        "playwright.sync_api",
        reason="playwright is not installed: the browser claim was NOT measured.",
    )
    with real_relay() as (port, _factory), _publisher(port) as pub:
        pub.send(json.dumps(links_frame({"lnk_e2e": SHARE_TOKEN})))
        pub.send(json.dumps({"type": "size", "link_id": "lnk_e2e", "cols": 120, "rows": 30}))
        requests: list = []
        sockets: list = []
        console: list = []
        with sync_api.sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--use-mock-keychain"])
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"chromium could not launch, NOT measured: {type(exc).__name__}")
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.on("request", lambda r: requests.append((r.url, r.all_headers())))
            page.on("websocket", lambda ws: sockets.append(ws.url))
            page.on("console", lambda m: console.append(m.text))
            page.goto(f"http://127.0.0.1:{port}/s/lnk_e2e#{SHARE_TOKEN}")
            deadline = time.monotonic() + 15.0
            painted = False
            while time.monotonic() < deadline and not painted:
                pub.send(json.dumps(data_frame("lnk_e2e", "hello from the relay\r\n")))
                page.wait_for_timeout(200)
                painted = "hello from the relay" in (
                    page.text_content(".xterm-rows") or "")
            assert painted, f"the stream never painted; console: {console[-5:]}"

            pub.send(json.dumps(data_frame("lnk_e2e", "W" * 120 + "\r\n")))
            page.wait_for_timeout(300)
            rows = page.eval_on_selector_all(".xterm-rows > div", "els => els.map(e => e.textContent)")
            assert len(rows) == 30, len(rows)
            assert any("W" * 120 in row for row in rows), rows
            stage = page.eval_on_selector(
                ".spectate-stage",
                "el => [getComputedStyle(el).overflowX, el.scrollWidth, el.clientWidth]")
            assert stage[0] == "auto" and stage[1] > stage[2], stage

            pub.close()
            page.wait_for_selector('[data-spectate-state="ended"]', timeout=10000)
            browser.close()

    assert requests, "the browser recorded no requests at all"
    for url, headers in requests:
        assert SHARE_TOKEN not in url, url
        assert all(SHARE_TOKEN not in value for value in headers.values()), url
    assert sockets == [f"ws://127.0.0.1:{port}/watch/lnk_e2e"], sockets
    assert not [line for line in console if "Content Security Policy" in line], console


def test_in_a_real_browser_a_wrong_token_shows_the_refused_screen():
    sync_api = pytest.importorskip(
        "playwright.sync_api",
        reason="playwright is not installed: the browser claim was NOT measured.",
    )
    with real_relay() as (port, _factory), _publisher(port) as pub:
        pub.send(json.dumps(links_frame({"lnk_e2e": SHARE_TOKEN})))
        with sync_api.sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--use-mock-keychain"])
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"chromium could not launch, NOT measured: {type(exc).__name__}")
            page = browser.new_page()
            attempts = []
            page.on("websocket", lambda ws: attempts.append(ws.url))
            page.goto(f"http://127.0.0.1:{port}/s/lnk_e2e#not-the-right-token")
            page.wait_for_timeout(2500)
            assert page.get_attribute(".spectate-notice", "data-spectate-state") == "connecting"
            page.wait_for_selector('[data-spectate-state="refused"]', timeout=30000)
            page.wait_for_timeout(1500)
            assert len(attempts) == 5, attempts
            browser.close()

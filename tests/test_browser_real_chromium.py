
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_brw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_brw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.browser_routes import router as rest_router
from src.api.browser_socket import router as ws_router
from src.config.browser import BrowserConfig
from src.core.browsers import store
from src.core.browsers.manager import CHROME_APP, BrowserManager, profile_processes
from src.core.db_migration import ensure_db_migrated

JWT_SECRET = "test-secret-for-real-browser"

playwright = pytest.importorskip("playwright")


def _chromium_present() -> bool:
    if CHROME_APP.is_dir():
        return True
    cache = Path.home() / "Library/Caches/ms-playwright"
    return any(cache.glob("chromium_headless_shell-*")) if cache.is_dir() else False


pytestmark = pytest.mark.skipif(not _chromium_present(), reason="no chromium installed")


@pytest.fixture(autouse=True)
def patched_auth_config(monkeypatch):
    from src.config import settings as real_settings

    fake_auth = SimpleNamespace(
        jwt_secret=JWT_SECRET, jwt_expiry_minutes=60,
        access_token_ttl_seconds=900, refresh_token_ttl_seconds=604800,
        refresh_grace_seconds=10, totp_secret="X" * 32,
    )

    class _FakeSettings:
        def load_auth_config(self):
            return fake_auth

        def __getattr__(self, name):
            return getattr(real_settings, name)

    monkeypatch.setattr("src.api.auth.settings", _FakeSettings())


def _token() -> str:
    payload = {"exp": datetime.utcnow() + timedelta(minutes=60),
               "iat": datetime.utcnow(), "sub": "claudetunnel_user", "typ": "access"}
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


POPPER = (
    b"<body style='margin:0'><div id=b style='position:fixed;inset:0'></div><script>"
    b"document.getElementById('b').onclick=()=>{for(let i=0;i<10;i++)"
    b"window.open('/pop?n='+i,'_blank');};"
    b"setInterval(()=>{for(let i=0;i<5;i++)if(window.open('/pop?bg=1','_blank'))"
    b"sessionStorage.opened=+(sessionStorage.opened||0)+1},20);"
    b"</script>"
)


class _Page(BaseHTTPRequestHandler):

    def do_GET(self):  # noqa: N802
        if self.path == "/":
            body = (b"<a href='/clicked?token=T' style='position:fixed;inset:0;"
                    b"display:block'>go</a>")
        elif self.path == "/popper":
            body = POPPER
        else:
            body = b"<p>clicked</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _listening_pids(pids) -> str:
    out = subprocess.run(
        ["lsof", "-nP", "-a", "-p", ",".join(map(str, pids)), "-iTCP", "-sTCP:LISTEN"],
        capture_output=True, text=True, timeout=20)
    assert out.returncode in (0, 1), out.stderr
    return out.stdout


def test_the_listener_check_can_go_red():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        assert "LISTEN" in _listening_pids([os.getpid()])


def _receive_until(ws, predicate, seconds: float = 30.0, limit: int = 400):
    watchdog = threading.Timer(seconds, ws.close)
    watchdog.start()
    try:
        for _ in range(limit):
            message = ws.receive()
            if message.get("type") == "websocket.close":
                raise AssertionError(f"closed before the expected message: {message}")
            if predicate(message):
                return message
    finally:
        watchdog.cancel()
    raise AssertionError("predicate never satisfied")


def _text(kind):
    return lambda m: m.get("text") and json.loads(m["text"])["type"] == kind


def test_a_real_chromium_end_to_end(tmp_path):
    assert ensure_db_migrated(tmp_path).status == "ok"
    manager = BrowserManager(tmp_path, lambda: BrowserConfig(max_live=2))

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await manager.aclose()

    app = FastAPI(lifespan=lifespan)
    app.state.browser_manager = manager
    app.include_router(rest_router, prefix="/api/v1")
    app.include_router(ws_router)
    app.dependency_overrides[require_auth] = lambda: True
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{server.server_address[1]}"
    protocols = ["cloude.jwt.v1", _token()]

    try:
        with TestClient(app) as client:
            created = client.post("/api/v1/browsers", json={})
            assert created.status_code == 201, created.text
            browser = created.json()
            bid = browser["id"]
            assert browser["state"] == "live" and browser["url"] == "about:blank"
            profile = store.profile_dir(tmp_path, bid)
            assert oct(profile.stat().st_mode & 0o777) == "0o700"
            pids = profile_processes(profile)
            assert pids, "no chromium process found on the profile"
            command = subprocess.run(["ps", "-o", "command=", "-p", ",".join(map(str, pids))],
                                     capture_output=True, text=True).stdout
            assert "--remote-debugging-pipe" in command
            assert "--remote-debugging-port" not in command
            assert "--no-sandbox" not in command
            assert _listening_pids(pids) == ""

            with client.websocket_connect(f"/ws/browser?browser_id={bid}",
                                          subprotocols=protocols) as ws:
                meta = json.loads(_receive_until(ws, _text("meta"))["text"])
                assert meta["width"] > 0 and meta["height"] > 0
                frame = _receive_until(ws, lambda m: m.get("bytes"))["bytes"]
                assert frame[:2] == b"\xff\xd8", "not a JPEG"

                ws.send_text(json.dumps({"type": "navigate", "url": site + "/"}))
                _receive_until(ws, lambda m: m.get("text") and json.loads(m["text"]).get(
                    "url") == site + "/" and json.loads(m["text"]).get("loading") is False)
                for event in ("down", "up"):
                    ws.send_text(json.dumps({"type": "mouse", "event": event, "x": 100,
                                             "y": 100, "button": "left", "clickCount": 1}))
                clicked = _receive_until(ws, lambda m: m.get("text") and json.loads(
                    m["text"]).get("url", "").startswith(site + "/clicked"))
                assert json.loads(clicked["text"])["type"] == "nav"

                for pid in profile_processes(profile):
                    os.kill(pid, signal.SIGKILL)
                stopped = json.loads(_receive_until(ws, _text("stopped"))["text"])
                assert stopped["reason"] in ("exited", "crashed")
            listed = client.get("/api/v1/browsers").json()["browsers"]
            assert [(b["id"], b["state"]) for b in listed] == [(bid, "stopped")]
            assert listed[0]["url"] == site + "/clicked", "stored with its query"

            with client.websocket_connect(f"/ws/browser?browser_id={bid}",
                                          subprotocols=protocols) as ws:
                first = _receive_until(ws, lambda m: m.get("text") is not None)
                assert json.loads(first["text"])["type"] == "restarted"
                _receive_until(ws, lambda m: m.get("text") and json.loads(m["text"]).get(
                    "url") == site + "/clicked")

            assert client.delete(f"/api/v1/browsers/{bid}").status_code == 204
            assert not profile.parent.exists()
            deadline = time.monotonic() + 10
            while profile_processes(profile) and time.monotonic() < deadline:
                time.sleep(0.1)
            assert profile_processes(profile) == []
            assert client.get("/api/v1/browsers").json()["browsers"] == []
    finally:
        server.shutdown()


@pytest.fixture()
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _headless_shell() -> str:
    import re as _re

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        build = _re.search(r"chromium-(\d+)", pw.chromium.executable_path)
    if not build:
        return ""
    found = sorted((Path.home() / "Library/Caches/ms-playwright").glob(
        f"chromium_headless_shell-{build.group(1)}/*/chrome-headless-shell"))
    return str(found[0]) if found else ""


@pytest.mark.parametrize("binary", ["ladder", "headless-shell"])
def test_a_page_cannot_fan_windows_out(tmp_path, site, binary):
    import asyncio

    executable = None
    if binary == "headless-shell":
        executable = _headless_shell() or pytest.skip("no matching headless shell")

    async def scenario():
        manager = BrowserManager(tmp_path, lambda: BrowserConfig(executable=executable))
        live = await manager.launch(store.new_id(), site + "/popper")
        created = []
        try:
            live.context.on("page", lambda page: created.append(page))
            await asyncio.sleep(2.0)
            opened = int(await live.page.evaluate("+(sessionStorage.opened||0)"))
            for event in ("down", "up"):
                await live.handle({"type": "mouse", "event": event, "x": 50, "y": 50,
                                   "button": "left", "clickCount": 1}, may_resize=True)
            most = 0
            deadline = asyncio.get_running_loop().time() + 3.0
            while asyncio.get_running_loop().time() < deadline:
                most = max(most, len(live.context.pages))
                await asyncio.sleep(0.01)
            return opened, most, len(created), live.page.url
        finally:
            await manager.aclose()

    opened, most, created, url = asyncio.run(scenario())
    assert opened <= 1, f"{opened} gesture-free window.open calls got a window"
    allowed = 0 if binary == "headless-shell" else 2
    assert created <= allowed, f"{created} extra pages were created"
    assert most <= 2, f"{most} pages were alive at once"
    assert url.startswith(site + "/pop?"), url


def test_a_tokened_url_never_reaches_the_log(tmp_path):
    import asyncio

    from structlog.testing import capture_logs

    url = "http://127.0.0.1:9/cb?code=SENTINEL_TOKEN_42#frag"

    async def scenario():
        manager = BrowserManager(tmp_path, lambda: BrowserConfig())
        try:
            await manager.launch(store.new_id(), url)
        finally:
            await manager.aclose()

    with capture_logs() as logs:
        asyncio.run(scenario())
    failed = [e for e in logs if e["event"] == "browser_open_url_failed"]
    assert failed and failed[0]["error"].startswith("net::ERR_"), logs
    assert "SENTINEL_TOKEN_42" not in repr(logs)

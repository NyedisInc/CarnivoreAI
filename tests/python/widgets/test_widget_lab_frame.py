
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time

import pytest

from scripts.widgets import harness

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

PAGE = "/static/dist/widget-lab/index.html"
QUERY = "widget=core.notes&zone=home&size=m&theme=carnivore&fixture=data&lab=1"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_app():
    if not (harness.REPO / "client" / "dist" / "widget-lab" / "index.html").is_file():
        pytest.skip("client/dist/widget-lab/ is not built: run npm run build in web/")
    uvicorn = pytest.importorskip("uvicorn")
    from src.main import app  # noqa: PLC0415

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def page(live_app):
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed in this venv")
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=harness.CHROMIUM_ARGS)
        except Exception as exc:
            pytest.skip(f"no Playwright chromium here ({str(exc).splitlines()[0]})")
        yield browser.new_page(reduced_motion="reduce")
        browser.close()


def test_the_shipped_page_answers_framing_for_this_origin_only(live_app, page) -> None:
    page.goto(f"{live_app}/static/setup.html")
    csp = page.evaluate("async (u) => (await fetch(u)).headers.get('content-security-policy')", f"{live_app}{PAGE}")
    assert "frame-ancestors 'self'" in csp and "default-src 'self'" in csp
    near = page.evaluate("async (u) => (await fetch(u)).headers.get('content-security-policy')", f"{live_app}{PAGE}/")
    assert "frame-ancestors 'none'" in near


def test_a_same_origin_parent_frames_it_and_the_widget_draws(live_app, page) -> None:
    page.goto(f"{live_app}/static/setup.html")
    page.evaluate("""(src) => { const f = document.createElement('iframe'); f.id = 'lab'; f.src = src; f.width = 500; f.height = 500; document.body.append(f); }""",
                  f"{PAGE}?{QUERY}")
    page.wait_for_function("""() => { try { const w = document.getElementById('lab').contentWindow; return !!w.__widgetHarness && w.__widgetHarness.ready === true; }
        catch (e) { return false; } }""", timeout=30_000)
    drawn = page.evaluate("""() => { const w = document.getElementById('lab').contentWindow;
        return { error: w.__widgetHarness.error, text: (w.document.querySelector('.wh-stage') || {}).innerText || '', area: w.document.querySelector('textarea') ? w.document.querySelector('textarea').value : '' }; }""")
    assert drawn["error"] == "" and "NOTES" in drawn["text"] and "retry policy" in drawn["area"], drawn

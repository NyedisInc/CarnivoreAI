
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest


CLIENT = Path(__file__).resolve().parents[3] / "client"

PAGE = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="/css/layers.css"><link rel="stylesheet" href="/css/styles.css">
<link rel="stylesheet" href="/dist/app.css">
<link rel="stylesheet" href="/css/session-row-menu.css"><link rel="stylesheet" href="/css/session-sidebar.css">
<link rel="stylesheet" href="/css/session-sidebar-rows.css"><link rel="stylesheet" href="/css/session-sidebar-density.css">
<link rel="stylesheet" href="/css/config-editor.css"><link rel="stylesheet" href="/css/home-bar.css">
</head><body style="width:400px">
<div class="session-row-menu" style="position:static;display:block;width:240px"><button class="session-row-menu__item" id="menu-item"><span>close</span></button></div>
<div class="session-sidebar-row" id="sidebar-row" tabindex="0"><span>agent</span></div>
<div style="width:300px"><button class="config-editor-file" id="config-file"><span>notes.md</span></button></div>
<div class="home-bar"><button class="home-bar__btn" id="home-btn">x</button></div>
<script>window.go = () => { document.body.focus(); };</script>
</body></html>"""

PROBE = """async (id) => {
  const el = document.getElementById(id);
  const snap = () => { const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    return { w: r.width, h: r.height, border: cs.borderTopColor, bw: cs.borderTopWidth, shadow: cs.boxShadow }; };
  el.blur();
  const rest = snap();
  el.focus();
  const focused = { ...snap(), visible: el.matches(':focus-visible') };
  return { rest, focused };
}"""


@pytest.fixture(scope="module")
def page():
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: focus was NOT measured")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] == "/rings.html":
                body = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(CLIENT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            server.shutdown()
            pytest.skip(f"chromium unavailable: {exc}")
        pg = browser.new_page(viewport={"width": 600, "height": 500})
        pg.goto(f"http://127.0.0.1:{server.server_address[1]}/rings.html")
        pg.keyboard.press("Tab")
        yield pg
        browser.close()
    server.shutdown()


@pytest.mark.parametrize("control", ["menu-item", "sidebar-row", "config-file", "home-btn"])
def test_shared_rule_paints_the_border_and_nothing_else(page, control):
    got = page.evaluate(PROBE, control)
    rest, focused = got["rest"], got["focused"]
    assert focused["visible"], f"{control} did not match :focus-visible"
    assert focused["bw"] == "1px", f"{control} reserves no 1px border: {focused}"
    assert focused["border"] != rest["border"], f"{control}: the border did not move on focus: {got}"
    assert focused["shadow"] == "none" or focused["shadow"] == rest["shadow"], f"{control} still draws a ring: {got}"
    assert (focused["w"], focused["h"]) == (rest["w"], rest["h"]), f"{control} changed size on focus: {got}"

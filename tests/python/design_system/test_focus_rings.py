
from __future__ import annotations

import functools
import http.server
import re
import threading
from pathlib import Path

import pytest

from tests.python.design_system._sources import css_of

CLIENT = Path(__file__).resolve().parents[3] / "client"

RINGED = [
    ("session-row-menu.css", ".session-row-menu__item:focus-visible"),
    ("session-sidebar-density.css", ".session-sidebar-row:focus-visible"),
    ("config-editor.css", ".config-editor-file:focus-visible"),
    ("config-editor.css", ".config-editor-toggle:focus-visible"),
    ("home-bar.css", ".home-bar__btn:focus-visible"),
    ("home-bar.css", ".home-bar__link:focus-visible"),
]
RING = re.compile(r"box-shadow:\s*(?:inset\s+)?0\s+0\s+0\s+\d+px\s+var\(--(?:oc-orange|color-accent)\)")


def focus_rings(css: str, selector: str) -> list[str]:
    out = []
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        if selector in match.group(1) and RING.search(match.group(2)):
            out.append(match.group(2).strip())
    return out


def test_ring_scan_can_go_red():
    sample = ".x:focus-visible { box-shadow: inset 0 0 0 2px var(--oc-orange); }"
    assert focus_rings(sample, ".x:focus-visible")


@pytest.mark.parametrize(("sheet", "selector"), RINGED)
def test_no_own_focus_ring(sheet, selector):
    assert focus_rings(css_of(CLIENT / "css" / sheet), selector) == []


@pytest.mark.parametrize(
    ("sheet", "base"),
    [
        ("session-row-menu.css", ".session-row-menu .session-row-menu__item {"),
        ("config-editor.css", ".config-editor-file {"),
        ("home-bar.css", ".home-bar__link {"),
    ],
)
def test_reserved_transparent_border(sheet, base):
    css = css_of(CLIENT / "css" / sheet)
    block = css[css.index("\n" + base):].split("}", 1)[0]
    assert "border: 1px solid transparent" in block, f"{sheet} {base} lost its reserved border"


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

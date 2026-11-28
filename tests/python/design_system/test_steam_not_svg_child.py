
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the steam was NOT measured")
from playwright.sync_api import sync_playwright  # noqa: E402

CLIENT = Path(__file__).resolve().parents[3] / "client"

HARNESS = """<!DOCTYPE html>
<html><head>
<link rel="stylesheet" href="/css/layers.css">
<link rel="stylesheet" href="/css/session-sidebar-keep-awake.css">
</head><body><div id="host"></div>
<script type="module">
import { glyphSvg } from '/js/icons/glyphs.js';
window.glyphSvg = glyphSvg;
window.ready = true;
</script></body></html>
"""

WALK = """() => {
  const host = document.getElementById('host');
  host.innerHTML = '<button class="session-sidebar-row-keep-awake" data-keep-awake="1">' + window.glyphSvg('coffee', 13) + '</button>';
  const button = host.firstElementChild;
  // The wisps are driven by the shared 24 fps clock (issue #3265): it writes these custom properties on the wearer. Give each
  // wisp its own value and read back what the stylesheet painted, so a wisp wired to the wrong variable or not at all shows up.
  [1, 2, 3].forEach((n) => { button.style.setProperty('--amb-steam-op-' + n, String(n / 10)); button.style.setProperty('--amb-steam-y-' + n, String(-n)); });
  const wisps = [...host.querySelectorAll('.kaw-steam')];
  const bad = wisps.filter((w) => w instanceof SVGElement && !!w.ownerSVGElement);
  const first = wisps[0];
  const cup = host.querySelector('.kaw-cup');
  return {
    running: wisps.length, bad: bad.length,
    join: getComputedStyle(button).animationName,
    opacities: wisps.map((w) => Number(getComputedStyle(w).opacity)),
    u: cup && getComputedStyle(cup).getPropertyValue('--kaw-u').trim(),
    cupBox: first && cup ? [cup.getBoundingClientRect().width, cup.getBoundingClientRect().height] : null,
    wispBox: first ? [first.getBoundingClientRect().width, first.getBoundingClientRect().height] : null,
  };
}"""


@pytest.fixture(scope="module")
def page():
    body = HARNESS.encode()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] == "/harness.html":
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
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            server.shutdown()
            pytest.skip(f"chromium is not available, so the steam was NOT measured: {exc}")
        pg = browser.new_page()
        pg.goto(f"http://127.0.0.1:{server.server_address[1]}/harness.html")
        pg.wait_for_function("window.ready")
        yield pg
        browser.close()
    server.shutdown()


def test_steam_animates_the_outer_svg_not_a_path(page):
    r = page.evaluate(WALK)
    assert r["running"] == 3, f"expected the three steam wisps to run, got {r['running']}"
    assert r["bad"] == 0, "a steam animation targets an element inside an inline svg again (SVG layout per frame, issue #1821)"
    assert r["join"] == "amb-join-sparks-steam", "the cup must join the shared ambient clock (issue #3265)"
    assert r["opacities"] == [0.1, 0.2, 0.3], f"each wisp must read its own clock variable: {r['opacities']}"
    assert r["wispBox"] == r["cupBox"] == [13, 13], (r["wispBox"], r["cupBox"])
    assert float(r["u"]) == pytest.approx(13 / 16), "the travel must scale with the icon size"


from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the effort animations were NOT measured")
from playwright.sync_api import sync_playwright  # noqa: E402

CLIENT = Path(__file__).resolve().parents[3] / "client"

CSS_FILES = ["effort-level.css", "session-sidebar-colours.css", "session-sidebar-row-controls.css", "session-sidebar-rows.css"]

HARNESS = """<!DOCTYPE html>
<html><head>
<link rel="stylesheet" href="/css/layers.css">
%(links)s
<script src="/js/effort-level.js"></script>
<script src="/js/session-model-icon.js"></script>
</head><body><div id="host"></div></body></html>
"""

WALK = """(effort) => {
  const host = document.getElementById('host');
  host.innerHTML = window.SessionModelIcon.html('claude-opus-5', 5, effort);
  const mark = host.querySelector('.session-sidebar-row-model');
  const makesEffect = (el) => {
    const s = getComputedStyle(el);
    return (+s.opacity < 1) || /opacity|filter/.test(s.willChange) || s.filter !== 'none'
      || s.backdropFilter !== 'none' || (s.maskImage && s.maskImage !== 'none') || s.clipPath !== 'none'
      || s.mixBlendMode !== 'normal';
  };
  const name = (el) => el.tagName.toLowerCase() + '.' + el.className;
  const running = document.getAnimations().filter((a) => a.effect && a.effect.target && mark.contains(a.effect.target));
  const roots = [], backdrops = [];
  for (const a of running) {
    const t = a.effect.target;
    // A pseudo-element's animation runs inside its owner, so the owner counts as an ancestor of what moves.
    for (let el = a.effect.pseudoElement ? t : t.parentElement; el && el !== host; el = el.parentElement)
      if (makesEffect(el)) roots.push(name(t) + (a.effect.pseudoElement || '') + ' inside ' + name(el));
    if (getComputedStyle(t, a.effect.pseudoElement).backdropFilter !== 'none') backdrops.push(name(t) + (a.effect.pseudoElement || ''));
  }
  return { roots, backdrops, animations: running.length, markIsRoot: makesEffect(mark) };
}"""


@pytest.fixture(scope="module")
def page():
    links = "\n".join(f'<link rel="stylesheet" href="/css/{name}">' for name in CSS_FILES)
    body = (HARNESS % {"links": links}).encode()

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
            pytest.skip(f"chromium is not available, so the effort animations were NOT measured: {exc}")
        pg = browser.new_page()
        pg.goto(f"http://127.0.0.1:{server.server_address[1]}/harness.html")
        pg.wait_for_function("window.SessionModelIcon && window.EffortLevel")
        yield pg
        browser.close()
    server.shutdown()


@pytest.mark.parametrize("effort, animations", [("xhigh", 6), ("ultracode", 5), ("max", 2)])
def test_nothing_that_moves_sits_in_an_effect_root(page, effort, animations):
    r = page.evaluate(WALK, effort)
    assert r["roots"] == [], f"an effort animation runs inside an effect node (issue #1821): {r['roots']}"
    assert r["backdrops"] == [], f"an animated layer carries a backdrop-filter: {r['backdrops']}"
    assert not r["markIsRoot"], "the robot mark is an effect node again, so everything inside it is re-rendered per frame"
    assert r["animations"] == animations, f"{effort} must still run {animations} animations, got {r['animations']}"

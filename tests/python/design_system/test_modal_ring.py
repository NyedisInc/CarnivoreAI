
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parents[3] / "client"


PAGE = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="/css/layers.css"><link rel="stylesheet" href="/css/animation-pause.css"><link rel="stylesheet" href="/css/modal-glow.css">
</head><body><script src="/js/modal-ring.js"></script></body></html>"""

BUILD = """() => {
  const legacy = document.createElement('div');
  legacy.innerHTML = '<div class="modal-overlay"><div class="modal-content" id="a"><p>x</p></div></div>';
  document.body.appendChild(legacy);
  const lb = document.createElement('div');
  lb.innerHTML = '<div class="sidebar-help__lightbox-body" id="b"></div>';
  document.body.appendChild(lb);
  return new Promise((done) => requestAnimationFrame(() => setTimeout(done, 50)));
}"""

PROBE = """() => {
  const out = {};
  for (const id of ['a', 'b']) {
    const card = document.getElementById(id);
    const sheens = card.querySelectorAll(':scope > .mg-sheen');
    const span = sheens[0];
    out[id] = {
      count: sheens.length,
      hidden: span && span.getAttribute('aria-hidden'),
      animations: span ? span.getAnimations({ subtree: true }).map((a) => a.animationName) : [],
      hostName: span ? getComputedStyle(span).animationName : null,
      beforeName: span ? getComputedStyle(span, '::before').animationName : null,
      after: getComputedStyle(card, '::after').content,
    };
  }
  return out;
}"""


@pytest.fixture(scope="module")
def browser_page():
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the ring was NOT measured")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] == "/ring.html":
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
        yield browser, f"http://127.0.0.1:{server.server_address[1]}/ring.html"
        browser.close()
    server.shutdown()


def _measure(browser_page, reduced: str):
    browser, url = browser_page
    page = browser.new_page(reduced_motion=reduced)
    page.goto(url)
    page.evaluate(BUILD)
    result = page.evaluate(PROBE)
    page.close()
    return result


def test_every_card_gets_one_span_that_turns_on_transform(browser_page):
    got = _measure(browser_page, "no-preference")
    for card in ("a", "b"):
        assert got[card]["count"] == 1, f"card {card} has {got[card]['count']} .mg-sheen children"
        assert got[card]["hidden"] == "true"
        assert got[card]["hostName"] == "amb-join-dialog-glow"
        assert got[card]["beforeName"] == "none"
        assert got[card]["after"] in ("none", "normal"), "the old ::after ring is still drawn"


def test_reduced_motion_stops_the_turn(browser_page):
    got = _measure(browser_page, "reduce")
    for card in ("a", "b"):
        assert got[card]["count"] == 1
        assert got[card]["hostName"] == "none"
        assert got[card]["beforeName"] == "none"
        assert got[card]["animations"] == []


from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the spark was NOT measured")
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

WALK = """([effort, wrap]) => {
  const host = document.getElementById('host');
  host.innerHTML = window.SessionModelIcon.html('claude-opus-5', 5, effort);
  const spark = host.querySelector('.session-sidebar-row-model__spark');
  if (wrap) {  // synthetic backdrop root around the real spark: proves the walk below can see one
    const w = document.createElement('div');
    w.className = 'synthetic-root';
    w.style.willChange = 'opacity';
    spark.parentElement.insertBefore(w, spark);
    w.appendChild(spark);
  }
  const mark = host.querySelector('.session-sidebar-row-model');
  const makesEffect = (el) => {
    const s = getComputedStyle(el);
    return (+s.opacity < 1) || /opacity|filter|transform/.test(s.willChange) || s.filter !== 'none'
      || s.backdropFilter !== 'none' || (s.maskImage && s.maskImage !== 'none') || s.clipPath !== 'none'
      || s.mixBlendMode !== 'normal';
  };
  const roots = [];
  for (let el = spark.parentElement; el && el !== host; el = el.parentElement) if (makesEffect(el)) roots.push(el.className);
  const a = spark.getBoundingClientRect(), m = mark.getBoundingClientRect();
  return {
    roots, markIsRoot: makesEffect(mark), markContainsSpark: mark.contains(spark),
    animations: document.getAnimations().filter((x) => x.effect.target && spark.contains(x.effect.target)).length,
    inset: [m.left - a.left, m.top - a.top, a.right - m.right, a.bottom - m.bottom].map((v) => Math.round(v * 10) / 10),
  };
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
            pytest.skip(f"chromium is not available, so the spark was NOT measured: {exc}")
        pg = browser.new_page()
        pg.goto(f"http://127.0.0.1:{server.server_address[1]}/harness.html")
        pg.wait_for_function("window.SessionModelIcon && window.EffortLevel")
        yield pg
        browser.close()
    server.shutdown()


@pytest.mark.parametrize("effort", ["xhigh", "max"])
def test_spark_is_a_sibling_of_the_backdrop_root_mark(page, effort):
    r = page.evaluate(WALK, [effort, False])
    assert not r["markIsRoot"], "the mark is a backdrop root again (the max rainbow is an opacity cross-fade, issue #1821)"
    assert not r["markContainsSpark"], "the spark is inside the mark again (2.5 to 8 times the GPU inside a backdrop root, issue #1821)"
    assert r["roots"] == [], f"an ancestor of the spark creates an effect node: {r['roots']}"
    assert r["animations"] == 2, "the spark must still run its two motes"
    assert r["inset"] == [3, 3, 3, 3], f"the spark must sit 3px around the 16px mark, got {r['inset']}"


@pytest.mark.parametrize("effort", ["xhigh", "max"])
def test_the_walk_sees_a_synthetic_backdrop_root(page, effort):
    r = page.evaluate(WALK, [effort, True])
    assert r["roots"] == ["synthetic-root"], f"the walk cannot see a backdrop root, so the guard above proves nothing: {r['roots']}"


from __future__ import annotations

import functools
import http.server
import re
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the type switches were NOT measured")
from playwright.sync_api import sync_playwright  # noqa: E402

CLIENT = Path(__file__).resolve().parents[3] / "client"
APP_CSS = (CLIENT / "dist" / "app.css").read_text(encoding="utf-8")


def _hash(pattern: str) -> str:
    found = re.search(pattern, APP_CSS)
    assert found, f"{pattern} is not in client/dist/app.css: the component moved, update this harness"
    return found.group(1)


RING = _hash(r"\.oc-frame\[data-oc-focus\]\.(svelte-\w+):not\(\.oc-frame-terminal\)")
NUDGE = _hash(r"\.oc-resize-guide-chevron\.(svelte-\w+)\{")

CASES = {
    "status-lights": '<span class="status-led" data-outer="active" data-inner="working"></span>',
    "avatar-spiral": '<span class="session-sidebar-bar__avatar"><svg class="spiral-turn"></svg></span>',
    "terminal-ring": f'<div class="oc-frame {RING}" data-oc-focus></div>',
    "dialog-glow": '<div class="popup-focus"></div>',
    "effort-badges": '<span class="effort-level effort--xhigh"></span>',
    "drawer-bands": (
        '<div class="session-sidebar-row" data-kind="layout" data-layout-anim="shimmer"><span class="session-sidebar-row-name">'
        + '<span class="band-fx-host"><span class="band-fx">' + '<i data-t="x"></i>' * 24 + '</span></span></span></div>'
    ),
    "sparks-steam": '<span class="session-sidebar-row-model__spark"></span>',
    "busy-pulses": '<span class="session-sidebar-row-workflow-icon"></span>',
    "attention-cues": f'<span class="oc-resize-guide-chevron {NUDGE}"></span>',
    "pop-ins": '<div class="config-editor-picker-content"></div>',
}

HARNESS = """<!DOCTYPE html>
<html><head>
<link rel="stylesheet" href="/css/layers.css">
%(links)s
<link rel="stylesheet" href="/dist/app.css">
<style>.tt { transition: opacity 1s; opacity: 1; }</style>
<script src="/js/motion-setting.js"></script>
<script src="/vendor/xterm/xterm.js"></script>
<script type="module">
  import { createEffect } from '/css/themes/_shared/effects-base.js';
  window.__draws = 0;
  window.__fx = createEffect({ id: 'probe', fps: 60, setup: () => ({}), draw: () => { window.__draws += 1; } });
  window.__ready = true;
</script>
</head><body><div id="host"></div></body></html>
"""

CSS_FILES = [
    "status-led.css", "session-sidebar-account-chip.css", "popup-focus.css", "effort-level.css",
    "session-sidebar-colours.css", "session-sidebar-row-controls.css", "session-sidebar-rows.css",
    "config-drawer.css", "animation-pause.css", "animation-types.css",
]

KEY = "carnivore.animation-types-off"

SET_OFF = """(ids) => {
  if (ids.length) localStorage.setItem(%r, ids.join(' ')); else localStorage.removeItem(%r);
  window.MotionSetting.apply();
}""" % (KEY, KEY)

COUNT = """(html) => {
  const host = document.getElementById('host');
  host.innerHTML = html;
  const n = document.getAnimations().filter((a) => host.contains(a.effect.target)).length;
  host.innerHTML = '';
  return n;
}"""

TRANSITIONS = """() => {
  const host = document.getElementById('host');
  host.innerHTML = '<div class="tt" id="tt"></div>';
  const el = document.getElementById('tt');
  el.offsetWidth;
  el.style.opacity = '0';
  const n = document.getAnimations().filter((a) => a.effect.target === el).length;
  host.innerHTML = '';
  return n;
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
            pytest.skip(f"chromium is not available, so the type switches were NOT measured: {exc}")
        pg = browser.new_page()
        pg.goto(f"http://127.0.0.1:{server.server_address[1]}/harness.html")
        pg.wait_for_function("window.__ready === true")
        yield pg
        browser.close()
    server.shutdown()


def _counts(page) -> dict[str, int]:
    counts = {tid: page.evaluate(COUNT, html) for tid, html in CASES.items()}
    counts["transitions"] = page.evaluate(TRANSITIONS)
    return counts


def test_every_type_runs_with_everything_on(page):
    page.evaluate(SET_OFF, [])
    counts = _counts(page)
    assert all(n > 0 for n in counts.values()), counts


@pytest.mark.parametrize("type_id", [*CASES, "transitions"])
def test_switching_one_type_off_stops_only_that_type_and_on_resumes_it(page, type_id):
    page.evaluate(SET_OFF, [])
    base = _counts(page)
    page.evaluate(SET_OFF, [type_id])
    off = _counts(page)
    assert page.evaluate("document.documentElement.getAttribute('data-anim-off')") == type_id
    assert off[type_id] == 0, f"{type_id} still runs with its switch off: {off}"
    others = {k: v for k, v in off.items() if k != type_id}
    assert others == {k: v for k, v in base.items() if k != type_id}, f"another type changed: {off} vs {base}"
    page.evaluate(SET_OFF, [])
    assert _counts(page)[type_id] == base[type_id], "switching it back on did not resume it"


def test_theme_backdrop_loop_stops_and_resumes(page):
    page.evaluate(SET_OFF, [])
    page.evaluate("() => { window.__draws = 0; window.__fx.init(); }")
    page.wait_for_timeout(300)
    running = page.evaluate("window.__draws")
    assert running > 0, "the backdrop loop never drew with everything on"
    page.evaluate(SET_OFF, ["theme-backdrop"])
    page.wait_for_timeout(100)
    held = page.evaluate("window.__draws")
    page.wait_for_timeout(300)
    assert page.evaluate("window.__draws") == held, "the backdrop kept drawing with its switch off"
    page.evaluate(SET_OFF, [])
    page.wait_for_timeout(300)
    assert page.evaluate("window.__draws") > held, "the backdrop did not resume"
    page.evaluate("() => window.__fx.destroy()")


def test_cursor_blink_option_follows_the_switch(page):
    page.evaluate(SET_OFF, [])
    page.evaluate("() => { window.__term = new Terminal({ cursorBlink: true }); window.Motion.bindCursorBlink(window.__term); }")
    assert page.evaluate("window.__term.options.cursorBlink") is True
    page.evaluate(SET_OFF, ["cursor-blink"])
    page.wait_for_timeout(50)
    assert page.evaluate("window.__term.options.cursorBlink") is False
    page.evaluate(SET_OFF, [])
    page.wait_for_timeout(50)
    assert page.evaluate("window.__term.options.cursorBlink") is True


from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the animations setting was NOT measured")
from playwright.sync_api import sync_playwright  # noqa: E402

CLIENT = Path(__file__).resolve().parents[3] / "client"

HARNESS = """<!DOCTYPE html>
<html><head>
<link rel="stylesheet" href="file://%(css)s/layers.css">
<link rel="stylesheet" href="file://%(css)s/effort-level.css">
<link rel="stylesheet" href="file://%(css)s/animation-pause.css">
<script>
  /* A stand-in for the preference layer: a stored value and the one subscriber PreferenceBridge.follow keeps. */
  window.__stored = undefined;
  window.__follower = null;
  window.PreferenceBridge = {
    read: function (field, local) { return window.__stored === undefined ? local() : window.__stored; },
    follow: function (field, apply) { window.__follower = apply; return function () {}; },
  };
</script>
<script src="file://%(js)s/motion-setting.js"></script>
</head><body>
<span id="max" class="effort-level effort--max">max</span>
<span id="xhigh" class="effort-level effort--xhigh">xhigh</span>
<span id="ultra" class="effort-level effort--ultracode">ultracode</span>
<span id="high" class="session-sidebar-row-model effort-level effort--high"><svg width="10" height="10"></svg></span>
<div class="oc-tabpane-hidden"><span id="hidden-max" class="effort-level effort--max">max</span></div>
<div><span id="shown-max" class="effort-level effort--max">max</span></div>
</body></html>
"""

PROBE = """() => {
  const q = (id, pseudo) => getComputedStyle(document.getElementById(id), pseudo || null);
  return {
    attr: document.documentElement.getAttribute('data-motion'),
    reduced: window.Motion.reduced(),
    xhigh: q('xhigh').animationName,
    maxBefore: q('max', '::before').animationName,
    maxBeforeContent: q('max', '::before').content,
    ultraBeforeContent: q('ultra', '::before').content,
    highAfterContent: q('high', '::after').content,
  };
}"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    path = tmp_path_factory.mktemp("anim") / "harness.html"
    path.write_text(HARNESS % {"css": str(CLIENT / "css"), "js": str(CLIENT / "js")}, encoding="utf-8")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium is not available, so the animations setting was NOT measured: {exc}")
        pg = browser.new_page()
        pg.goto(path.as_uri())
        yield pg
        browser.close()


def test_animations_setting_turns_the_effort_animations_off_and_back_on(page):
    on = page.evaluate(PROBE)
    assert on["attr"] is None, "absent means on: no attribute"
    assert on["xhigh"] != "none" and on["maxBefore"] != "none", on
    assert on["maxBeforeContent"] != "none" and on["ultraBeforeContent"] != "none", on

    page.evaluate("() => window.__follower(false)")
    off = page.evaluate(PROBE)
    assert off["attr"] == "off", off
    assert off["reduced"] is True, off
    assert off["xhigh"] == "none" and off["maxBefore"] == "none", off
    assert off["maxBeforeContent"] == "none", off
    assert off["ultraBeforeContent"] == "none", off
    assert off["highAfterContent"] == "none", off

    page.evaluate("() => window.__follower(true)")
    back = page.evaluate(PROBE)
    assert back["attr"] is None and back["xhigh"] != "none" and back["maxBefore"] != "none", back


def test_a_hidden_tab_pane_pauses_the_effort_overlay_pseudo_elements(page):
    page.evaluate("() => window.__follower(true)")
    states = page.evaluate("""() => {
      const ps = (id, pseudo) => {
        const cs = getComputedStyle(document.getElementById(id), pseudo);
        return [cs.animationName, cs.animationPlayState];
      };
      return { hidden: ps('hidden-max', '::before'), shown: ps('shown-max', '::before') };
    }""")
    assert states["shown"][0] != "none" and states["shown"][1] == "running", states
    assert states["hidden"][0] != "none" and states["hidden"][1] == "paused", states

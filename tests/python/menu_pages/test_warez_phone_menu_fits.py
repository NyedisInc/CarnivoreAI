
from __future__ import annotations

import os

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed, so NO warez phone menu fit was measured.",
)
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("TESTSRV_BASE", "")
AUTH = os.environ.get("TESTSRV_AUTH", "")

pytestmark = pytest.mark.skipif(
    not (BASE and AUTH and os.path.exists(AUTH)),
    reason="TESTSRV_BASE/TESTSRV_AUTH not set: no leased slot, so NO warez phone menu fit was measured.",
)

PROBE = """
() => {
  const wm = document.querySelector('.wm');
  const tree = document.querySelector('.wm__tree');
  const foot = document.querySelector('.wm')?.closest('.oc-page') || document.body;
  if (!wm || !tree || !foot) return { present: false };
  tree.scrollTop = tree.scrollHeight;
  const rows = [...tree.querySelectorAll('.wm__row')];
  const last = rows[rows.length - 1].getBoundingClientRect();
  const hit = document.elementFromPoint(last.left + last.width / 2, last.top + last.height / 2);
  return {
    present: true,
    menuBottom: wm.getBoundingClientRect().bottom,
    footTop: foot.getBoundingClientRect().bottom,
    lastBottom: last.bottom,
    lastHit: !!hit && rows[rows.length - 1].contains(hit),
    scrollable: tree.scrollHeight > tree.clientHeight,
  };
}
"""


@pytest.mark.parametrize("height", [844, 667])
def test_phone_menu_fits_above_the_foot(height: int) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx = browser.new_context(
                storage_state=AUTH, viewport={"width": 390, "height": height}, has_touch=True
            )
            page = ctx.new_page()
            page.goto(f"{BASE}/#warez")
            page.wait_for_selector(".wm__row", timeout=30000)
            got = page.evaluate(PROBE)
        finally:
            browser.close()
    assert got["present"], "the phone menu screen did not render"
    assert got["menuBottom"] <= got["footTop"] + 1, got
    assert got["scrollable"] or got["lastBottom"] <= got["footTop"] + 1, got
    assert got["lastHit"], got
    assert got["lastBottom"] <= got["footTop"] + 1, got

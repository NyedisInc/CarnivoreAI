from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core import ui_preferences
from src.core.ui_preferences.values import UiPreferenceValues

from ._sources import split_selectors

ROOT = Path(__file__).resolve().parents[3]
GATE = ':root[data-row-lights="still"]'
FIELD = "row_lights_animate"
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")

ROWS = """
<style>@keyframes spin { to { transform: rotate(1turn); } }
.status-led { animation: spin 1s linear infinite; }</style>
<div class="session-sidebar-row" id="rest"><span class="status-led" id="rest-led"></span></div>
<div class="session-sidebar-row" id="sel" aria-selected="true"><span class="status-led" id="sel-led"></span></div>
"""
PROBE = """() => ({
  attr: document.documentElement.getAttribute('data-row-lights'),
  rest: getComputedStyle(document.getElementById('rest-led')).animationName,
  sel: getComputedStyle(document.getElementById('sel-led')).animationName,
})"""


@pytest.fixture(scope="module")
def browser():
    pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the lights setting was NOT measured")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium is not available, so the lights setting was NOT measured: {exc}")
        yield b
        b.close()


@pytest.fixture
def open_page(browser, tmp_path):
    from .test_animations_setting_renders import HARNESS

    html = HARNESS % {"css": str(ROOT / "client/css"), "js": str(ROOT / "client/js")}
    html = html.replace("</head>", '<link rel="stylesheet" href="file://%s/resting-row-lights.css"></head>' % (ROOT / "client/css"))
    html = html.replace("</body>", ROWS + "</body>")
    path = tmp_path / "lights.html"
    path.write_text(html, encoding="utf-8")

    def open_it(preset: str):
        page = browser.new_page()
        page.add_init_script("window.__preset = %s;" % preset)
        page.goto(path.as_uri())
        return page

    return open_it


def test_stored_false_stills_resting_rows_only_and_missing_or_true_leaves_them_moving(open_page) -> None:
    for preset in ("{}", "{%s: true}" % FIELD):
        on = open_page(preset).evaluate(PROBE)
        assert on["attr"] is None and on["rest"] == "spin" and on["sel"] == "spin", on
    off = open_page("{%s: false}" % FIELD).evaluate(PROBE)
    assert off["attr"] == "still", off
    assert off["rest"] == "none" and off["sel"] == "spin", "a selected row keeps moving: %s" % off


def test_a_live_follow_flips_the_attribute_and_the_rows(open_page) -> None:
    page = open_page("{}")
    page.evaluate("() => window.__followers.%s(false)" % FIELD)
    assert page.evaluate(PROBE)["attr"] == "still" and page.evaluate(PROBE)["rest"] == "none"
    page.evaluate("() => window.__followers.%s(true)" % FIELD)
    back = page.evaluate(PROBE)
    assert back["attr"] is None and back["rest"] == "spin", back


def test_never_fabricated_and_strict_boolean() -> None:
    assert FIELD in ui_preferences.known_fields()
    assert FIELD not in ui_preferences.empty_block()["values"]
    for bad in ("no", 0, 1, "false"):
        with pytest.raises(ValidationError):
            UiPreferenceValues(**{FIELD: bad})
    assert UiPreferenceValues(**{FIELD: False}).row_lights_animate is False


def _ungated(css: str) -> list[str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [sel for group, _ in RULE.findall(css) if "@layer" not in group for sel in split_selectors(group) if not sel.startswith(GATE)]


def test_the_sheet_is_linked_and_every_rule_is_gated() -> None:
    assert "/static/css/resting-row-lights.css" in (ROOT / "client/index.html").read_text()
    css = (ROOT / "client/css/resting-row-lights.css").read_text()
    assert "status-led" in css and "kaw-steam" in css, "the A5 still-row rules are missing"
    assert _ungated(css) == []


def test_negative_control_flags_an_ungated_selector_after_a_gated_one() -> None:
    planted = ':root[data-row-lights="still"] .status-led,\n.session-sidebar-row:not(:hover) .status-led { animation: none; }'
    assert _ungated(planted) == [".session-sidebar-row:not(:hover) .status-led"]

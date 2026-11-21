from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the split was NOT measured. Not a pass.")

from tests.python.design_system._sources import REPO, inline_css

ENTRY = REPO / "web" / "src" / "opscenter" / "app.css"
LAYERS = REPO / "client" / "css" / "layers.css"
SHELL = ":root { --overlay-top: 0px; } body { margin: 0; }"
TITLE = '<header class="oc-titlebar" data-frame-region="header" data-btn-density="frame"><h1 class="oc-titlebar__title">page</h1></header>'
LIST = '<div class="oc-page__scroll" id="list"><div class="oc-page__main"><p>the list</p></div></div>'
PANE = '<section class="oc-page__detail" id="pane"><div class="oc-page__detail-body"><p>the pane</p></div></section>'


def page(reading: bool, body_style: str = "") -> str:
    cls = "oc-page__split oc-page__split--reading" if reading else "oc-page__split"
    inner = LIST + (PANE if reading else "")
    return (
        f'<div class="oc-page" data-oc-base data-frame="column">{TITLE}'
        f'<div class="oc-page__body" data-scroll="self" data-frame-region="body" style="{body_style}"><div class="oc-page__fill">'
        f'<div class="{cls}" id="split">{inner}</div></div></div></div>'
    )


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the split was NOT measured. Not a pass.")
        yield chromium
        chromium.close()


def measure(browser, width: int, reading: bool, body_style: str = "", extra_css: str = "") -> dict:
    css = LAYERS.read_text() + inline_css(ENTRY) + SHELL + extra_css
    context = browser.new_context(viewport={"width": width, "height": 800})
    pg = context.new_page()
    try:
        pg.set_content(f"<!doctype html><html><head><style>{css}</style></head><body>{page(reading, body_style)}</body></html>")
        return pg.evaluate(
            """() => {
                const w = (s) => { const el = document.querySelector(s); return el ? Math.round(el.getBoundingClientRect().width) : null; };
                const shown = (s) => { const el = document.querySelector(s); return !!el && getComputedStyle(el).display !== 'none'; };
                const scrollers = [...document.querySelectorAll('.oc-page *')]
                    .filter((e) => ['auto', 'scroll'].includes(getComputedStyle(e).overflowY) && e.clientHeight > 0)
                    .map((e) => e.id || e.className.toString());
                return {body: w('.oc-page__body'), split: w('#split'), list: w('#list'), pane: w('#pane'),
                        listShown: shown('#list'), scrollers};
            }"""
        )
    finally:
        context.close()


def test_one_scroller_per_column(browser) -> None:
    got = measure(browser, 1440, True)
    assert got["scrollers"] == ["list", "oc-page__detail-body"], got["scrollers"]


def test_reading_split_is_three_to_two_at_desktop(browser) -> None:
    got = measure(browser, 1440, True)
    assert got["list"] and got["pane"], got
    assert abs(got["list"] / got["pane"] - 1.5) < 0.05, got
    assert got["list"] + got["pane"] == got["split"], got


def test_pane_replaces_the_list_on_a_narrow_window(browser) -> None:
    got = measure(browser, 390, True)
    assert not got["listShown"], got
    assert got["pane"] == got["split"], got


def test_pane_replaces_the_list_on_a_narrow_body_in_a_wide_window(browser) -> None:
    got = measure(browser, 1440, True, body_style="width: 600px")
    assert not got["listShown"], got
    assert got["pane"] == got["split"] == 600, got


def test_no_pane_is_one_full_width_column(browser) -> None:
    got = measure(browser, 1440, False)
    assert got["list"] == got["split"] == got["body"] and got["pane"] is None, got

from __future__ import annotations

import re

import pytest

from tests.python.design_system._sources import REPO, inline_css

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the nav body was NOT measured. Not a pass.")

ENTRY = REPO / "web" / "src" / "opscenter" / "app.css"
LAYERS = REPO / "client" / "css" / "layers.css"
SESSIONS_CSS = REPO / "web" / "src" / "lib" / "sessions-page" / "sessions-page.css"
SHELL = ":root { --overlay-top: 0px; } body { margin: 0; }"
VIEWPORT_H = 800
MIN_BODY_PX = 200
PHONE_WIDTHS = [409, 660]

TITLE = '<header class="oc-titlebar" data-frame-region="header" data-btn-density="frame"><h1 class="oc-titlebar__title">page</h1></header>'
AWAY = '<div class="oc-page__away"><div class="oc-page__bar" data-frame-region="tools" data-btn-density="frame"><span>tools</span></div></div>'
SIDE = '<aside class="oc-page__side" data-frame-region="side"><ul><li>lens</li></ul></aside>'
ROWS = "".join(f'<div class="row" style="height: 36px">row {i}</div>' for i in range(60))
SESSIONS_BODY = (
    '<div class="sp-body"><div class="sp-hosts"><div class="sp-host" id="host" data-host="list">'
    f"{ROWS}</div></div></div>"
)
GENERIC_BODY = (
    '<div style="display: flex; flex-direction: column; min-height: 0">'
    f'<div id="host" style="flex: 1 1 0; min-height: 0; overflow: auto">{ROWS}</div></div>'
)


def nav_page(body: str, scroll: str = "self") -> str:
    return (
        f'<div class="oc-page sp-page" data-oc-base data-frame="nav">{TITLE}'
        f'<div class="oc-page__frame" data-frame-region="frame" data-scroll="{scroll}">{SIDE}<div class="oc-page__col">{AWAY}'
        f'<div class="oc-page__body" data-scroll="{scroll}" data-frame-region="body"><div class="oc-page__fill">{body}</div></div>'
        "</div></div></div>"
    )


def column_page(body: str) -> str:
    return (
        f'<div class="oc-page" data-oc-base data-frame="column">{TITLE}{AWAY}'
        f'<div class="oc-page__body" data-scroll="self" data-frame-region="body"><div class="oc-page__fill">{body}</div></div></div>'
    )


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the nav body was NOT measured. Not a pass.")
        yield chromium
        chromium.close()


def measure(browser, width: int, markup: str) -> dict:
    css = LAYERS.read_text() + inline_css(ENTRY) + SESSIONS_CSS.read_text() + SHELL
    context = browser.new_context(viewport={"width": width, "height": VIEWPORT_H})
    try:
        page = context.new_page()
        page.set_content(f"<!doctype html><html><head><style>{css}</style></head><body>{markup}</body></html>")
        return page.evaluate(
            """() => {
                const h = (s) => Math.round(document.querySelector(s).getBoundingClientRect().height);
                const root = document.querySelector('.oc-page');
                return {body: h('.oc-page__body'), host: h('#host'), rootScrollable: root.scrollHeight > root.clientHeight + 1};
            }"""
        )
    finally:
        context.close()


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("body", [SESSIONS_BODY, GENERIC_BODY], ids=["sessions-page-sheet", "generic-list-host"])
def test_a_nav_pages_body_fills_the_phone_page(browser, width: int, body: str) -> None:
    got = measure(browser, width, nav_page(body))
    assert got["body"] > MIN_BODY_PX, f"the nav body is {got['body']}px tall at {width} (the page draws a blank): {got}"
    assert got["host"] > MIN_BODY_PX, f"the list host is {got['host']}px tall at {width}, the list is not visible: {got}"


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_column_frame_control_keeps_its_body(browser, width: int) -> None:
    got = measure(browser, width, column_page(SESSIONS_BODY))
    assert got["body"] > MIN_BODY_PX and got["host"] > MIN_BODY_PX, f"the column frame control lost its body at {width}: {got}"


def test_the_desktop_nav_body_is_unchanged(browser) -> None:
    got = measure(browser, 1440, nav_page(SESSIONS_BODY))
    assert got["body"] > MIN_BODY_PX and got["host"] > MIN_BODY_PX, f"the desktop nav body collapsed: {got}"


def test_a_scroll_frame_nav_page_still_grows_with_its_content_on_a_phone(browser) -> None:
    got = measure(browser, 409, nav_page(SESSIONS_BODY.replace('class="sp-host"', 'class="sp-host" style="flex: none; overflow: visible"'), scroll="frame"))
    assert got["rootScrollable"], f"a frame-scrolled nav page no longer scrolls its root: {got}"


SELF_SCROLLING_NAV_PAGES = {
    "web/src/lib/catalog/CatalogScreen.svelte",
    "web/src/lib/plugin-studio/StudioScreen.svelte",
    "web/src/lib/settings-page/SettingsScreen.svelte",
    "web/src/lib/sessions-page/SessionsPage.svelte",
    "web/src/lib/widgets-page/WidgetsScreen.svelte",
}
_NAV = re.compile(r'frame="nav"')
_SELF = re.compile(r'scroll="self"')


def test_every_self_scrolling_nav_page_is_named_here() -> None:
    found = {
        str(p.relative_to(REPO))
        for p in (REPO / "web" / "src").rglob("*.svelte")
        if p.name != "Page.svelte" and _NAV.search(p.read_text()) and _SELF.search(p.read_text())
    }
    assert found == SELF_SCROLLING_NAV_PAGES, f"a nav page that scrolls itself is not named in this test (add it, the frame rule covers it): {found ^ SELF_SCROLLING_NAV_PAGES}"

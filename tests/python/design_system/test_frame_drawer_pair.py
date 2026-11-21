from __future__ import annotations

import pytest

from tests.python.design_system._sources import REPO, inline_css

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the drawer pair was NOT measured. Not a pass.")

ENTRY = REPO / "web" / "src" / "opscenter" / "app.css"
LAYERS = REPO / "client" / "css" / "layers.css"
VIEWPORT_H = 800
SURFACE = (
    ":root { --overlay-top: 0px; --menu-surface-top: 40px; --menu-surface-left: 300px; --menu-surface-right: 0px;"
    " --menu-surface-bottom: 0px; --sidebar-dock-w: 320px; } body { margin: 0; }"
)
LIST_X, LIST_W, PAGE_W, RAIL_W = 300, 240, 640, 184

HEADER = '<header class="oc-titlebar" data-frame-region="header" data-btn-density="frame"><h1 class="oc-titlebar__title">{t}</h1></header>'
NAV = '<nav id="nav"><div style="height: 120px">rail</div></nav>'
TABS = '<div class="oc-page__away"><div class="oc-page__tabs" id="tabs" data-frame-region="tabs" data-btn-density="frame"><div>tab</div></div></div>'
BODY = (
    '<div class="oc-page__body" data-scroll="self" data-frame-region="body"><div class="oc-page__fill">'
    '<div id="content" style="height: {h}px">content</div></div></div>'
)
PAIR = (
    '<div class="oc-page oc-page--drawer-list" data-oc-base data-frame="nav" data-pair="list" id="list">'
    + HEADER.format(t="settings")
    + f'<div class="oc-page__frame" data-frame-region="frame" data-scroll="self" data-pair=""><aside class="oc-page__side" id="side" data-frame-region="side">{NAV}</aside></div></div>'
    + f'<div class="oc-page oc-page--drawer-stacked" data-oc-base data-frame="nav" data-pair="page" id="page" style="--oc-drawer-offset: {LIST_W}px">'
    + HEADER.format(t="appearance")
    + '<div class="oc-page__frame" data-frame-region="frame" data-scroll="self" data-pair=""><div class="oc-page__col">'
    + TABS + BODY.format(h=300) + "</div></div></div>"
)


def one_page(side: bool, content_h: int) -> str:
    aside = f'<aside class="oc-page__side" id="side" data-frame-region="side">{NAV}</aside>' if side else ""
    return (
        '<div class="oc-page" data-oc-base data-frame="nav" data-pair="one" id="root">' + HEADER.format(t="settings")
        + f'<div class="oc-page__frame" id="frame" data-frame-region="frame" data-scroll="self" data-pair="">{aside}<div class="oc-page__col">'
        + TABS + BODY.format(h=content_h) + "</div></div></div>"
    )


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the drawer pair was NOT measured. Not a pass.")
        yield chromium
        chromium.close()


@pytest.fixture(scope="module")
def css() -> str:
    return LAYERS.read_text() + inline_css(ENTRY) + SURFACE


def measure(browser, css: str, width: int, markup: str, body_class: str = "") -> dict:
    context = browser.new_context(viewport={"width": width, "height": VIEWPORT_H}, reduced_motion="reduce")
    page = context.new_page()
    try:
        page.set_content(f'<!doctype html><html><head><style>{css}</style></head><body class="{body_class}">{markup}</body></html>')
        return page.evaluate(
            """() => {
                const box = (id) => { const el = document.getElementById(id); if (!el) return null; const b = el.getBoundingClientRect();
                    return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]; };
                const out = {};
                for (const id of ['list', 'page', 'root', 'frame', 'side', 'nav', 'tabs', 'content']) out[id] = box(id);
                for (const id of ['list', 'page']) { const el = document.getElementById(id); if (el) out[id + 'Z'] = Number(getComputedStyle(el).zIndex); }
                const root = document.getElementById('root');
                if (root) out.rootScroll = [root.scrollHeight, root.clientHeight];
                const tabs = document.getElementById('tabs');
                if (tabs) out.tabsPad = parseFloat(getComputedStyle(tabs).paddingLeft);
                return out;
            }"""
        )
    finally:
        context.close()


@pytest.mark.parametrize("width", [1440, 1100])
def test_at_drawer_widths_the_pair_is_a_list_drawer_and_a_page_drawer_beside_it(browser, css: str, width: int) -> None:
    got = measure(browser, css, width, PAIR, "menu-page-surface")
    assert got["list"][:3] == [LIST_X, 40, LIST_W], f"the list drawer left the surface edge or its floor: {got}"
    page_w = min(PAGE_W, width - LIST_X - LIST_W)
    assert got["page"][:3] == [LIST_X + LIST_W, 40, page_w], f"the page drawer is not beside the list at its floor: {got}"
    assert got["listZ"] > got["pageZ"], f"the page drawer must slide out from under the list: {got}"
    assert got["side"][2] == LIST_W, f"the side does not fill the list drawer: {got}"
    assert got["nav"][3] == got["side"][3] == VIEWPORT_H - 40 - 37, f"the rail does not fill the list drawer top to bottom: {got}"


def test_below_drawer_widths_the_pair_is_one_page_with_the_rail_beside_the_column(browser, css: str) -> None:
    got = measure(browser, css, 900, one_page(side=True, content_h=300))
    assert got["side"][2] == RAIL_W, f"the rail is not the pair's width: {got}"
    assert got["nav"][3] == got["side"][3] >= VIEWPORT_H - 44, f"the rail does not run to the bottom of the page: {got}"
    assert got["tabs"][0] == RAIL_W, f"the tab row does not start beside the rail: {got}"


def test_the_rail_holds_its_place_when_the_frame_is_narrow(browser, css: str) -> None:
    got = measure(browser, css, 900, one_page(side=True, content_h=300), "session-sidebar-pinned")
    assert got["frame"][2] < 720, f"the dock did not narrow the frame, so this proves nothing: {got}"
    assert got["side"] is not None and got["side"][2] == RAIL_W, f"the rail folded away: {got}"


@pytest.mark.parametrize("width", [900, 390])
def test_below_1024_the_page_root_is_the_one_scroller(browser, css: str, width: int) -> None:
    got = measure(browser, css, width, one_page(side=width >= 768, content_h=2000))
    scroll_h, client_h = got["rootScroll"]
    assert got["content"][3] == 2000, f"the planted content is not there: {got}"
    assert scroll_h > client_h + 1000, f"the body clipped the content instead of letting the page root scroll: {got}"


def test_on_a_phone_the_tab_row_runs_flush(browser, css: str) -> None:
    got = measure(browser, css, 390, one_page(side=False, content_h=300))
    assert got["tabsPad"] == 0, f"the phone tab row is inset; its first cell carries the gutter itself: {got}"

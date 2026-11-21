from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so the phone scroll was NOT measured. Not a pass.")

REPO = Path(__file__).resolve().parents[3]
ENTRY = REPO / "web" / "src" / "opscenter" / "app.css"
LAYERS = REPO / "client" / "css" / "layers.css"
SWARM_SOURCES = (
    REPO / "web" / "src" / "lib" / "huddle-swarm" / "SwarmPage.svelte",
    REPO / "web" / "src" / "lib" / "swarm-board" / "views" / "SwimlanesView.svelte",
)
_IMPORT = re.compile(r"""@import\s+(?:url\()?['"](\.[^'"]+)['"]\)?\s*;""")
_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
_GLOBAL = re.compile(r":global\(([^()]*)\)")
SHELL = ":root { --overlay-top: 0px; } body { margin: 0; }"
SCROLL_PX = 1500
VIEWPORT_H = 800

TITLE = '<header class="oc-titlebar" data-frame-region="header" data-btn-density="frame"><h1 class="oc-titlebar__title">page</h1></header>'
TALL = '<div id="{id}" style="height: 4000px">content</div>'
GENERIC = (
    f'<div class="oc-page" data-oc-base data-frame="column">{TITLE}'
    '<div class="oc-page__body" data-scroll="self" data-frame-region="body"><div class="oc-page__fill"><div>'
    '<div id="row" style="position: sticky; top: var(--oc-frame-sticky-top); height: 30px">row</div>'
    f'{TALL.format(id="content")}</div></div></div></div>'
)
SWARM = (
    f'<div class="oc-page" data-oc-base data-frame="column">{TITLE}'
    '<div class="oc-page__body" data-scroll="self" data-frame-region="body"><div class="oc-page__fill">'
    '<div class="pkg-body" id="scroller"><div class="sbs"><div class="sbs-main">'
    '<div class="sbs-cols" id="row"><span>todo</span><span>doing</span><span>review</span><span>done</span></div>'
    f'{TALL.format(id="content")}</div></div></div></div></div></div>'
)
ROWS = (
    '<div class="oc-page__away"><div class="oc-page__tabs" data-frame-region="tabs" data-btn-density="frame">'
    '<div class="oc-ptabs" id="tabs"><div class="oc-ptabs__list" role="tablist">'
    '<button type="button" class="oc-ptab" role="tab" aria-selected="true" id="tab">board</button></div></div></div></div>'
)
STICKY_JS = REPO / "client" / "js" / "frame-sticky-top.js"
CANVAS = (
    f'<div class="oc-page" data-oc-base data-frame="canvas">{TITLE}'
    '<div class="oc-page__body" data-scroll="self" data-frame-region="body" id="body"><div class="oc-page__fill">'
    '<div style="height: 100%"></div></div></div></div>'
)


def inline_css(path: Path) -> str:
    text = path.read_text()
    return _IMPORT.sub(lambda m: inline_css((path.parent / m.group(1)).resolve()), text)


def component_css(path: Path) -> str:
    return "\n".join(_GLOBAL.sub(r"\1", block) for block in _STYLE.findall(path.read_text()))


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the phone scroll was NOT measured. Not a pass.")
        yield chromium
        chromium.close()


def render(browser, width: int, markup: str):
    css = LAYERS.read_text() + inline_css(ENTRY) + "".join(component_css(p) for p in SWARM_SOURCES) + SHELL
    context = browser.new_context(viewport={"width": width, "height": VIEWPORT_H})
    page = context.new_page()
    page.set_content(f"<!doctype html><html><head><style>{css}</style></head><body>{markup}</body></html>")
    return context, page


def tops(page) -> dict:
    return page.evaluate(
        """() => {
            const at = (s, edge) => { const el = document.querySelector(s); return el ? Math.round(el.getBoundingClientRect()[edge]) : null; };
            return {title: at('.oc-titlebar', 'bottom'), row: at('#row', 'top'), content: at('#content', 'top'), scroller: at('#scroller', 'top')};
        }"""
    )


def scrolled(browser, width: int, markup: str) -> tuple[dict, dict]:
    context, page = render(browser, width, markup)
    try:
        before = tops(page)
        page.mouse.move(width / 2, VIEWPORT_H / 2)
        page.mouse.wheel(0, SCROLL_PX)
        page.wait_for_timeout(200)
        return before, tops(page)
    finally:
        context.close()


@pytest.mark.parametrize("markup", [GENERIC, SWARM], ids=["fill-row", "swarm-board-row"])
@pytest.mark.parametrize("width", [390, 740])
def test_below_the_phone_line_a_sticky_row_stays_under_the_title_strip(browser, width: int, markup: str) -> None:
    before, after = scrolled(browser, width, markup)
    assert before["content"] - after["content"] >= SCROLL_PX - 2, f"nothing scrolled at {width}: {before} -> {after}"
    assert after["title"] - 1 <= after["row"] < VIEWPORT_H, f"the sticky row left the screen at {width}: {before} -> {after}"


def test_from_the_phone_line_up_the_body_scrolls_and_the_board_row_stays_put(browser) -> None:
    before, after = scrolled(browser, 1440, SWARM)
    assert before["content"] - after["content"] >= SCROLL_PX - 2, f"nothing scrolled: {before} -> {after}"
    assert after["scroller"] == before["scroller"], "the page root moved; the body should be the scroller from 768 up"
    assert abs(after["row"] - before["row"]) <= 1, f"the board row moved with the content instead of pinning: {before} -> {after}"


def test_a_canvas_body_keeps_a_real_box_above_the_phone_line(browser) -> None:
    context, page = render(browser, 740, CANVAS)
    try:
        height = page.evaluate("() => Math.round(document.querySelector('#body').getBoundingClientRect().height)")
    finally:
        context.close()
    assert height >= VIEWPORT_H / 2, f"the canvas body is {height}px tall at 740; its page has no box to size a surface from"


ROWS_PROBE = """() => {
    const box = (s) => document.querySelector(s).getBoundingClientRect();
    const tab = box('#tab');
    const hit = document.elementFromPoint(tab.left + 5, tab.top + tab.height / 2);
    return {title: Math.round(box('.oc-titlebar').bottom), rows: Math.round(box('.oc-page__away').bottom), row: Math.round(box('#row').top),
            content: Math.round(box('#content').top), tabHit: !!(hit && hit.closest('#tab'))};
}"""


def with_rows(browser, width: int, markup: str) -> tuple[dict, dict]:
    page_markup = markup.replace(TITLE, TITLE + ROWS, 1)
    script = STICKY_JS.read_text() + "\nwindow.watchFrameStickyTop = watchFrameStickyTop;"
    context, page = render(browser, width, page_markup)
    try:
        page.add_script_tag(content=script, type="module")
        page.wait_for_function("() => typeof window.watchFrameStickyTop === 'function'")
        page.evaluate("() => { window.stopSticky = window.watchFrameStickyTop(document.querySelector('.oc-page')); }")
        before = page.evaluate(ROWS_PROBE)
        page.mouse.move(width / 2, VIEWPORT_H / 2)
        page.mouse.wheel(0, SCROLL_PX)
        page.wait_for_timeout(200)
        shown = page.evaluate(ROWS_PROBE)
        assert before["content"] - shown["content"] >= SCROLL_PX - 2, f"nothing scrolled at {width}: {before} -> {shown}"
        page.evaluate("() => document.querySelector('.oc-page').classList.add('oc-page--away')")
        page.wait_for_timeout(500)
        return shown, page.evaluate(ROWS_PROBE)
    finally:
        context.close()


@pytest.mark.parametrize("markup", [GENERIC, SWARM], ids=["fill-row", "swarm-board-row"])
@pytest.mark.parametrize("width", [390, 740])
def test_below_the_phone_line_a_sticky_row_rests_under_the_tab_rows_while_they_show(browser, width: int, markup: str) -> None:
    shown, _ = with_rows(browser, width, markup)
    assert shown["rows"] > shown["title"], f"the planted rows are not under the strip: {shown}"
    assert shown["rows"] - 1 <= shown["row"] < VIEWPORT_H, f"the sticky row sits over the tab rows at {width}: {shown}"
    assert shown["tabHit"], f"a tap on the tab lands on something else at {width}: {shown}"


@pytest.mark.parametrize("markup", [GENERIC, SWARM], ids=["fill-row", "swarm-board-row"])
@pytest.mark.parametrize("width", [390, 740])
def test_below_the_phone_line_a_sticky_row_rises_to_the_strip_when_the_rows_slide_away(browser, width: int, markup: str) -> None:
    _, away = with_rows(browser, width, markup)
    assert away["rows"] <= away["title"] + 1, f"the rows did not slide away behind the strip: {away}"
    assert abs(away["row"] - away["title"]) <= 1, f"the sticky row did not rise to the strip at {width}: {away}"

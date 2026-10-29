
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so NOTHING about the browser screen's "
        "inset or the shift close x was measured. Not a pass."
    ),
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TERMINAL_GRID_CSS = REPO_ROOT / "client" / "css" / "terminal-grid.css"
ROW_CONTROLS_CSS = REPO_ROOT / "client" / "css" / "session-sidebar-row-controls.css"
BROWSER_SCREEN_SVELTE = REPO_ROOT / "web" / "src" / "lib" / "browser" / "BrowserScreen.svelte"

SHELL_WIDTH = 900
SHELL_HEIGHT = 600
SIDE_RAIL_WIDTH = 40


def _svelte_style(path: Path) -> str:
    match = re.search(r"<style>(.*?)</style>", path.read_text(encoding="utf-8"), re.S)
    assert match, f"{path} has no style block; the screen's own sizing cannot be read"
    return match.group(1)


def _inset_html(with_grid: bool) -> str:
    grid_children = (
        '<div class="oc-surface" style="height:100%"></div>'
        f'<div data-session-rail data-rail-edge="side" style="width:{SIDE_RAIL_WIDTH}px"></div>'
        if with_grid
        else '<div class="terminal-container" style="flex:1"></div>'
    )
    css = TERMINAL_GRID_CSS.read_text(encoding="utf-8") + _svelte_style(BROWSER_SCREEN_SVELTE)
    return (
        "<!DOCTYPE html><html><head><style>"
        f"html,body{{margin:0}} #terminal-screen{{display:flex;flex-direction:column;"
        f"width:{SHELL_WIDTH}px;height:{SHELL_HEIGHT}px}}"
        f"{css}</style></head><body>"
        '<div id="terminal-screen"><div id="terminal-grid">'
        f"{grid_children}"
        '<div id="browser-screen"><div class="bscreen"><div class="bs-body"></div></div></div>'
        "</div></div></body></html>"
    )


_ROW = (
    '<div class="session-sidebar-row" data-shift-close="1"><div class="session-sidebar-row-main">'
    '<span class="name">row</span>'
    '<button type="button" class="session-row-menu-trigger" data-row-menu aria-expanded="{expanded}">m</button>'
    '<span class="session-sidebar-row-shift-close">'
    '<button type="button" class="session-sidebar-row-key session-sidebar-row-key--close" '
    'data-browser-row-action="close">x</button></span></div></div>'
)


def _rows_html() -> str:
    rows = _ROW.format(expanded="false") * 2 + _ROW.format(expanded="true")
    css = ROW_CONTROLS_CSS.read_text(encoding="utf-8")
    return f"<!DOCTYPE html><html><head><style>{css}</style></head><body><div id='list'>{rows}</div></body></html>"


@pytest.fixture()
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}), so nothing was measured. Not a pass.")
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        pg = context.new_page()
        try:
            yield pg
        finally:
            context.close()
            browser.close()


_MEASURE = """() => {
    const box = (el) => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
    const host = document.getElementById('browser-screen');
    const screen = host.querySelector('.bscreen');
    const area = document.querySelector('#terminal-grid > .oc-surface, #terminal-grid > .terminal-container');
    return {
        host: box(host), screen: box(screen), area: box(area), grid: box(document.getElementById('terminal-grid')),
        overflowX: host.scrollWidth - host.clientWidth, overflowY: host.scrollHeight - host.clientHeight,
        docOverflow: document.documentElement.scrollHeight - document.documentElement.clientHeight,
    };
}"""


@pytest.mark.parametrize("with_grid", [True, False], ids=["desktop-grid", "flex-column"])
def test_browser_screen_sits_one_pixel_in_from_every_edge(page, with_grid: bool) -> None:
    page.set_content(_inset_html(with_grid))
    m = page.evaluate(_MEASURE)
    want_host = m["area"] if with_grid else m["grid"]
    assert m["host"] == want_host, f"#browser-screen {m['host']} is not the main section {want_host}"
    left, top, right, bottom = m["host"]
    assert m["screen"] == [left + 1, top + 1, right - 1, bottom - 1], (
        f"the screen {m['screen']} is not 1px in from the main section {m['host']} on every side"
    )
    assert (m["overflowX"], m["overflowY"], m["docOverflow"]) == (0, 0, 0), f"the inset overflows: {m}"
    if with_grid:
        assert right == SHELL_WIDTH - SIDE_RAIL_WIDTH, "the screen runs under the side rail"


_SHIFT_STATE = """() => Array.from(document.querySelectorAll('.session-sidebar-row')).map((row) => ({
    x: getComputedStyle(row.querySelector('.session-sidebar-row-shift-close')).display,
    kebab: getComputedStyle(row.querySelector('.session-row-menu-trigger')).visibility,
}))"""


def test_every_shift_held_row_shows_its_x_and_none_after_release(page) -> None:
    page.set_content(_rows_html())
    page.mouse.move(1200, 780)
    held = page.evaluate(_SHIFT_STATE)
    assert held[:2] == [{"x": "flex", "kebab": "hidden"}] * 2, (
        f"an unhovered, unfocused row does not show its x while Shift is held: {held}"
    )
    assert held[2] == {"x": "none", "kebab": "visible"}, f"a row whose menu is open lost its kebab: {held[2]}"

    page.evaluate("document.querySelectorAll('[data-shift-close]').forEach((r) => r.removeAttribute('data-shift-close'))")
    released = page.evaluate(_SHIFT_STATE)
    assert released == [{"x": "none", "kebab": "visible"}] * 3, f"an x outlived the Shift key: {released}"

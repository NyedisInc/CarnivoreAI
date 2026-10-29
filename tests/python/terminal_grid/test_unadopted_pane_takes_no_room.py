
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed, so NOTHING about the terminal grid was measured. Not a pass.",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TERMINAL_GRID_CSS = REPO_ROOT / "client" / "css" / "terminal-grid.css"

SHELL_WIDTH = 1000
SHELL_HEIGHT = 800
SIDE_RAIL_WIDTH = 36
BOTTOM_RAIL_HEIGHT = 30
XTERM_HEIGHT = 760


def _grid_html() -> str:
    css = TERMINAL_GRID_CSS.read_text(encoding="utf-8")
    return (
        "<!DOCTYPE html><html><head><style>"
        "html,body{margin:0}"
        f"#terminal-screen{{display:flex;flex-direction:column;width:{SHELL_WIDTH}px;height:{SHELL_HEIGHT}px}}"
        ".oc-surface{height:100%;display:flex;flex-direction:column}"
        "[data-cell]{flex:1;display:flex;flex-direction:column;min-height:0}.oc-frame-body{flex:1}"
        ".terminal-container{flex:1;display:flex;flex-direction:column;min-height:0}"
        f"{css}</style></head><body>"
        '<div id="terminal-screen"><div id="terminal-grid">'
        '<div id="browser-screen"></div>'
        f'<div class="terminal-container" id="terminal-container"><div class="xterm" style="height:{XTERM_HEIGHT}px"></div></div>'
        '<div class="oc-surface"><div data-cell="terminal:@primary"><div class="oc-frame-body"></div></div></div>'
        f'<nav data-session-rail data-rail-edge="bottom" style="height:{BOTTOM_RAIL_HEIGHT}px"></nav>'
        f'<nav data-session-rail data-rail-edge="side" style="width:{SIDE_RAIL_WIDTH}px"></nav>'
        "</div></div></body></html>"
    )


@pytest.fixture()
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}), so nothing was measured. Not a pass.")
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        pg = context.new_page()
        try:
            yield pg
        finally:
            context.close()
            browser.close()


_MEASURE = """() => {
    const height = (sel) => document.querySelector(sel).getBoundingClientRect().height;
    const pane = document.getElementById('terminal-container');
    return {
        grid: height('#terminal-grid'),
        surface: height('#terminal-grid > .oc-surface'),
        side: height('[data-rail-edge="side"]'),
        pane: pane.getBoundingClientRect().height,
        paneDisplay: getComputedStyle(pane).display,
        body: height('.oc-frame-body'),
    };
}"""


def test_an_unadopted_pane_takes_no_room_and_an_adopted_one_fills_its_cell(page) -> None:
    page.set_content(_grid_html())
    before = page.evaluate(_MEASURE)
    assert before["grid"] == SHELL_HEIGHT, f"the harness grid is not the screen's height: {before}"
    assert before["surface"] == SHELL_HEIGHT - BOTTOM_RAIL_HEIGHT, (
        f"the unadopted pane took the surface's row: surface {before['surface']}px of {SHELL_HEIGHT}px ({before})"
    )
    assert before["side"] == SHELL_HEIGHT, f"the side rail lost its full height to the unadopted pane: {before}"
    assert before["pane"] == 0, f"the unadopted pane still has a box: {before}"

    page.evaluate("document.querySelector('.oc-frame-body').appendChild(document.getElementById('terminal-container'))")
    after = page.evaluate(_MEASURE)
    assert after["paneDisplay"] != "none", f"the adopted pane is not drawn: {after}"
    assert after["surface"] == SHELL_HEIGHT - BOTTOM_RAIL_HEIGHT, f"the surface lost its row after the adoption: {after}"
    assert after["pane"] == after["body"] > 0, f"the adopted pane does not fill its cell: {after}"

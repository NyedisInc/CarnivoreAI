
from __future__ import annotations

import functools
import http.server
import re
import socketserver
import threading
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed, so NO sidebar row geometry was measured.",
)

from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
CLIENT_ROOT = REPO_ROOT / "client"

EPSILON_PX = 0.5

ROW_WIDTHS = [440, 320, 300, 290, 280, 275, 272, 265, 260, 250, 245, 240, 230, 220, 210]

OPTIONAL = ["agents", "shells", "timers"]

_GLYPH = '<svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true"></svg>'


def _stylesheets() -> list[str]:
    html = (CLIENT_ROOT / "index.html").read_text(encoding="utf-8")
    return re.findall(r'<link rel="stylesheet" href="/static/([^"?]+)"', html)


def _icon(kind: str) -> str:
    return (f'<span class="session-sidebar-row-{kind}-icon" role="img" '
            f'aria-label="{kind}" title="{kind}">{_GLYPH}</span>')


def _row(name: str, icons: list[str], cup: bool) -> str:
    optional = "".join(_icon(kind) for kind in OPTIONAL if kind in icons)
    group = f'<span class="session-sidebar-row-optional-icons">{optional}</span>' if optional else ""
    cup_html = (f'<button type="button" class="session-sidebar-row-keep-awake">{_GLYPH}</button>'
                if cup else "")
    return (
        f'<div class="session-sidebar-row" data-name="{name}" role="option">'
        '<div class="session-sidebar-row-main">'
        '<span class="status-dot status-dot--idle status-led" role="img"></span>'
        '<span class="session-sidebar-row-provider" role="img">'
        '<svg width="16" height="16" viewBox="0 0 24 24"></svg></span>'
        '<span class="session-sidebar-row-model" role="img">'
        '<svg width="14" height="14" viewBox="0 0 20 20"></svg></span>'
        f'<span class="session-sidebar-row-name">{name}</span>'
        '<span class="session-sidebar-row-controls-cluster">'
        f'{group}{cup_html}'
        f'<button type="button" class="session-sidebar-row-pin">{_GLYPH}</button>'
        '<button type="button" class="session-row-menu-trigger">...</button>'
        '</span></div></div>'
    )


PAGE = """<!doctype html><html><head><meta charset="utf-8">{links}</head>
<body style="margin:0">
<aside class="session-sidebar-panel session-sidebar-panel--open" data-density="compact"
       style="--sidebar-dock-w: 520px">
  <div class="session-sidebar-list" id="list"></div>
</aside></body></html>"""

MEASURE = """
([html, width]) => {
  const list = document.getElementById('list');
  list.innerHTML = '<div style="width:' + width + 'px">' + html + '</div>';
  const row = list.querySelector('.session-sidebar-row');
  const box = row.getBoundingClientRect();
  const within = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return getComputedStyle(el).display !== 'none' && r.width > 0
      && r.left >= box.left - 0.5 && r.right <= box.right + 0.5;
  };
  const group = row.querySelector('.session-sidebar-row-optional-icons');
  const g = group ? group.getBoundingClientRect() : null;
  const painted = {};
  for (const kind of ['agents', 'shells', 'timers']) {
    const el = row.querySelector('.session-sidebar-row-' + kind + '-icon');
    if (!el) continue;
    const r = el.getBoundingClientRect();
    painted[kind] = getComputedStyle(el).display !== 'none' && r.width > 0 && g !== null
      && r.top >= g.top - 0.5 && r.bottom <= g.bottom + 0.5 && r.right <= g.right + 0.5
      && r.left >= g.left - 0.5;
  }
  const name = row.querySelector('.session-sidebar-row-name');
  return {
    rowWidth: box.width,
    painted,
    pin: within(row.querySelector('.session-sidebar-row-pin')),
    kebab: within(row.querySelector('.session-row-menu-trigger')),
    cup: within(row.querySelector('.session-sidebar-row-keep-awake')),
    nameWidth: name.getBoundingClientRect().width,
    nameFloor: parseFloat(getComputedStyle(name).minWidth),
  };
}
"""


class _Quiet(http.server.SimpleHTTPRequestHandler):

    page = ""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            body = self.page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/static/"):
            self.path = self.path[len("/static"):]
        super().do_GET()

    def log_message(self, *_args) -> None:
        pass


@pytest.fixture(scope="module")
def page() -> Iterator[object]:
    links = "".join(f'<link rel="stylesheet" href="/static/{p}">' for p in _stylesheets())
    handler = functools.partial(_Quiet, directory=str(CLIENT_ROOT))
    _Quiet.page = PAGE.format(links=links)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                tab = browser.new_page(viewport={"width": 1280, "height": 800})
                tab.goto(f"http://127.0.0.1:{server.server_address[1]}/")
                tab.wait_for_load_state("load")
                assert tab.evaluate("document.hidden") is False
                yield tab
                browser.close()
        finally:
            server.shutdown()


def _measure(tab: object, html: str, width: int) -> dict:
    result = tab.evaluate(MEASURE, [html, width])  # type: ignore[attr-defined]
    assert abs(result["rowWidth"] - width) <= EPSILON_PX, result
    return result


@pytest.mark.parametrize("width", [w for w in ROW_WIDTHS if w >= 220])
def test_a_quiet_row_keeps_its_timers_icon(page: object, width: int) -> None:
    got = _measure(page, _row("Garden Planner 2026", ["timers"], cup=False), width)
    assert got["painted"] == {"timers": True}, (
        f"a {width}px row hid its only icon although it had room: {got}")
    assert got["pin"] and got["kebab"], got


def test_a_crowded_row_gives_way_right_to_left_and_keeps_its_controls(page: object) -> None:
    html = _row("Agent - Cloude Code session with a long name",
                ["agents", "shells", "timers"], cup=True)
    seen_drop = False
    for width in ROW_WIDTHS:
        got = _measure(page, html, width)
        shown = [kind for kind in OPTIONAL if got["painted"][kind]]
        assert shown == OPTIONAL[:len(shown)], (
            f"at {width}px the icons gave way out of order: {got['painted']}")
        assert got["pin"] and got["kebab"] and got["cup"], (
            f"at {width}px a control left the row: {got}")
        assert got["nameWidth"] >= got["nameFloor"] - EPSILON_PX, (
            f"at {width}px the name went under its floor: {got}")
        if width >= 320:
            assert shown == OPTIONAL, f"a {width}px row had room for every icon: {got}"
        seen_drop = seen_drop or len(shown) < len(OPTIONAL)
    assert seen_drop, "no width tested made the crowded row give anything up"

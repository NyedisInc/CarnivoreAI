
from __future__ import annotations

import json
import os
import urllib.request

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed, so NO menu page cover was measured.",
)
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("TESTSRV_BASE", "")
AUTH = os.environ.get("TESTSRV_AUTH", "")

pytestmark = pytest.mark.skipif(
    not (BASE and AUTH and os.path.exists(AUTH)),
    reason="TESTSRV_BASE/TESTSRV_AUTH not set: no leased slot, so NO menu page cover was measured.",
)

PAGES = ["Sessions", "Projects", "Catalog", "Plugins", "Wrappers", "Hosts", "Themes", "Settings", "Widgets", "Ledger", "Blueprints"]

CONTAINERS = [f"{name.lower()}-screen" for name in PAGES]

ALLOWED = "#session-sidebar-panel, #session-sidebar-rail, #menu-page-bar, #toast-container"

PROBE = """
([containerId, allowed]) => {
  const root = document.getElementById(containerId)?.firstElementChild;
  const misses = [];
  let total = 0;
  for (let y = 2; y < innerHeight; y += 20) for (let x = 2; x < innerWidth; x += 20) {
    total++;
    const el = document.elementFromPoint(x, y);
    if (el && ((root && root.contains(el)) || el.closest(allowed))) continue;
    misses.push(`${x},${y} ${el ? el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + el.className : '(none)'}`);
  }
  return { total, misses: misses.slice(0, 8), missCount: misses.length, open: !!root };
}
"""


def _token() -> str:
    with open(AUTH, encoding="utf-8") as fh:
        state = json.load(fh)
    return next(
        item["value"]
        for item in state["origins"][0]["localStorage"]
        if item["name"] == "claude_tunnel_token"
    )


def _api(method: str, path: str, body: dict | None = None) -> object:
    req = urllib.request.Request(
        BASE + path,
        method=method,
        headers={"Authorization": "Bearer " + _token(), "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read() or b"null")


def _a_session() -> tuple[str, str]:
    listing = _api("GET", "/api/v1/sessions/list")
    rows = listing if isinstance(listing, list) else listing.get("sessions", [])
    if not rows:
        _api("POST", "/api/v1/sessions", {
            "project_name": "menu-cover", "working_dir": "~", "agent_type": "shell",
            "auto_start_claude": True, "copy_templates": False,
        })
        listing = _api("GET", "/api/v1/sessions/list")
        rows = listing if isinstance(listing, list) else listing.get("sessions", [])
    return rows[0]["session"]["id"], rows[0]["tmux_session"]


@pytest.mark.parametrize(
    ("width", "height", "drawer"),
    [(1440, 900, "docked"), (1440, 900, "railed"), (390, 844, "phone")],
)
def test_every_menu_page_covers_the_terminal(width: int, height: int, drawer: str) -> None:
    sid, tmux = _a_session()
    phone = drawer == "phone"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(
            storage_state=AUTH, viewport={"width": width, "height": height},
            device_scale_factor=3 if phone else 1, is_mobile=phone, has_touch=phone,
        )
        page = ctx.new_page()
        page.goto(BASE + "/")
        page.wait_for_function("window.CloudeWeb && window.CloudeWeb.openSettingsScreen", timeout=20000)
        assert page.evaluate("document.hidden") is False
        page.evaluate("([s, t]) => window.CloudeWeb.launchpad.openRunningSession(s, t)", [sid, tmux])
        page.wait_for_function("document.querySelector('#terminal-screen.active')", timeout=20000)
        page.wait_for_timeout(800)
        if drawer == "railed":
            page.evaluate("window.SessionSidebar.close()")
            page.wait_for_function("document.body.classList.contains('session-sidebar-railed')", timeout=5000)
        elif drawer == "docked":
            page.evaluate("window.SessionSidebar.open()")
            page.wait_for_function("document.body.classList.contains('session-sidebar-pinned')", timeout=5000)
        failures = []
        for name in PAGES:
            page.evaluate(f"() => window.CloudeWeb.open{name}Screen()")
            container = f"{name.lower()}-screen"
            page.wait_for_function(f"document.getElementById('{container}').firstElementChild", timeout=10000)
            page.wait_for_timeout(300)
            result = page.evaluate(PROBE, [container, ALLOWED])
            assert result["open"], name
            if result["missCount"]:
                failures.append(f"{name}: {result['missCount']}/{result['total']} points reach the screen behind: {result['misses']}")
            others = page.evaluate(
                "([c, ids]) => ids.filter(id => id !== c && document.getElementById(id)?.firstElementChild)",
                [container, CONTAINERS],
            )
            if others:
                failures.append(f"{name}: other pages still up {others}")
        if phone:
            page.click("#menu-page-bar button")
            page.wait_for_function("document.querySelector('#session-sidebar-panel.session-sidebar-panel--open')", timeout=5000)
        browser.close()
    assert not failures, "\n".join(failures)

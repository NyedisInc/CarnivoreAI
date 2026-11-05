"""Nothing on the Home dashboard may cover an open bottom or right drawer, and Home fills exactly its slot (issue #2774).

Joe (ccsliinc), 2026-11-03: "at some points the homepage takes over the whole screen and covers the bottom and right
drawer ... nothing should be able to cover the opened drawers." Reload ruling, same day: "Home in its slot, with the last
session's drawers open beside it, the way you left it."

Against ONE isolated validation server (a leased ``scripts/testsrv`` slot, never the live app), at 1440x900, with one seeded
shell session whose right drawer (files) and bottom drawer (scheduled tasks) are open, under each theme in ``--themes``,
every way Home can come up or be disturbed:

  home from the session | home from a menu page (settings) | home from the sessions page | a menu page opened over Home and
  closed with Escape | history back then forward | the window narrowed below 1024 and widened | Home entered narrow, then
  widened | the right drawer closed and reopened while Home is up | a reload while Home is up

and in EACH state, where the window is 1024 or wider, checks that

  1. both drawers are still PAINTED (a hit test at the middle of each lands inside the drawer),
  2. the Home screen's box does not intersect either drawer's box, and
  3. Home fills exactly the main area's cell (the terminal surface's own box, laid out under it) and nothing else.

Where the window is under 1024 it checks that Home is the plain full screen. Screenshots of every state go to ``--shots``.
Exit codes: 0 PASS, 1 FAIL, 2 CANNOT DETERMINE.

Run: venv/bin/python3 scripts/verify/home_over_drawers/verify_home_over_drawers.py --base http://127.0.0.1:8102 \\
         --storage-state <TESTSRV_AUTH> [--themes carnivore,dracula] [--shots DIR]
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, Error as PlaywrightError, Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from scripts.lib.verify_harness import Report, call, refuse_live_target, run_main, set_theme  # noqa: E402

WIDE = (1440, 900)
NARROW = (1000, 800)
SEED_NAME = "pa"
OTHER_NAME = "pb"
SETTLE_MS = 1500
FILL_TOLERANCE_PX = 1.5
RIGHT_KEY = "files"
BOTTOM_KEY = "scheduled tasks"
NEEDED_DRAWERS = {"session-widget-rail", "session-widget-rail-bottom"}

MEASURE_JS = """() => {
  const box = (e) => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  const home = document.getElementById('launchpad-screen');
  const homeShown = getComputedStyle(home).display !== 'none' && home.getBoundingClientRect().width > 0;
  const surface = document.querySelector('#terminal-grid > .oc-surface');
  const drawers = [...document.querySelectorAll('[data-session-rail], .rail-out')].map((el) => {
    const r = el.getBoundingClientRect();
    const hit = r.width > 0 && r.height > 0 ? document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) : null;
    return { name: el.id || el.className.toString().split(' ')[0], box: box(el), painted: !!hit && el.contains(hit), empty: r.width === 0 || r.height === 0 };
  });
  return { homeBox: homeShown ? box(home) : null, surfaceBox: surface ? box(surface) : null, drawers,
           width: window.innerWidth, height: window.innerHeight };
}"""


WS_LOG_JS = """(() => {
  const Native = window.WebSocket;
  window.__wsLog = [];
  window.WebSocket = function (url, protocols) { window.__wsLog.push(String(url)); return new Native(url, protocols); };
  window.WebSocket.prototype = Native.prototype;
  Object.assign(window.WebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
})();"""


def intersects(a: list[float], b: list[float]) -> bool:
    return min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1


def same_box(a: list[float], b: list[float]) -> bool:
    return all(abs(x - y) <= FILL_TOLERANCE_PX for x, y in zip(a, b))


def check_state(report: Report, page: Page, tag: str, want_open: bool = True) -> None:
    got = page.evaluate(MEASURE_JS)
    home = got["homeBox"]
    report.check(home is not None, f"{tag}: Home is showing", home)
    if home is None:
        return
    if got["width"] < 1024:
        report.check(same_box(home, [0, 0, got["width"], home[3]]), f"{tag}: narrow Home is the plain full screen", home)
        return
    drawers = [d for d in got["drawers"] if not d["empty"]]
    names = {d["name"] for d in drawers}
    report.check(NEEDED_DRAWERS <= names, f"{tag}: both drawers are on screen", sorted(names))
    if want_open:
        report.check("rail-out" in names, f"{tag}: the drawers' slide-outs are open", sorted(names))
    for d in drawers:
        report.check(d["painted"], f"{tag}: {d['name']} is painted, nothing over it", d["box"])
        report.check(not intersects(home, d["box"]), f"{tag}: Home does not overlap {d['name']}", home)
    surface = got["surfaceBox"]
    report.check(surface is not None and same_box(home, surface), f"{tag}: Home fills exactly its slot", [home, surface])


def seed_session(args: argparse.Namespace, name: str) -> None:
    rows = call(args, "/sessions/list")
    items = rows if isinstance(rows, list) else rows.get("sessions", [])
    if any(f"_{name}" in str(r.get("tmux_session", r)) for r in items):
        return
    call(args, "/sessions", "POST", {"project_name": name, "working_dir": "~", "agent_type": "shell",
                                     "auto_start_claude": True, "copy_templates": False})


def toggle_drawer(page: Page, rail: str, label: str) -> None:
    page.click(f'#{rail} button[aria-label="{label}"]')
    page.wait_for_timeout(700)


def shoot(page: Page, shots: str | None, name: str) -> None:
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(shots) / f"{name}.png"))


def fresh(browser: Browser, args: argparse.Namespace, size: tuple[int, int] = WIDE) -> Page:
    ctx = browser.new_context(storage_state=args.storage_state, viewport={"width": size[0], "height": size[1]})
    page = ctx.new_page()
    page.goto(args.base + "/", wait_until="domcontentloaded")
    page.wait_for_selector(".session-sidebar-row", timeout=20000)
    page.wait_for_timeout(SETTLE_MS)
    page.keyboard.press("Escape")
    if size[0] >= 1024:
        page.locator(f'.session-sidebar-row[data-name$="_{SEED_NAME}"]').first.click(timeout=10000)
        page.wait_for_selector("#session-widget-rail-bottom", timeout=20000)
        page.wait_for_timeout(SETTLE_MS)
        toggle_drawer(page, "session-widget-rail", RIGHT_KEY)
        toggle_drawer(page, "session-widget-rail-bottom", BOTTOM_KEY)
    return page


def go_home(page: Page) -> None:
    page.evaluate("App.showLaunchpad()")
    page.wait_for_timeout(SETTLE_MS)


def resize(page: Page, size: tuple[int, int]) -> None:
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.wait_for_timeout(SETTLE_MS * 2)


def scenarios(report: Report, browser: Browser, args: argparse.Namespace, theme: str) -> None:
    def case(name: str, run: Callable[[Page, str], None]) -> None:
        if args.only and args.only not in name:
            return
        page = fresh(browser, args)
        try:
            run(page, f"[{theme}] {name}")
            shoot(page, args.shots, f"{theme}-{name.replace(' ', '-')}")
        except PlaywrightError as exc:
            report.check(False, f"[{theme}] {name}: the case could not run", f"{type(exc).__name__}: {str(exc)[:120]}")
        finally:
            page.context.close()

    def from_session(page, tag):
        go_home(page)
        check_state(report, page, tag)

    def from_menu(page, tag):
        page.evaluate("CloudeWeb.openSettingsScreen()")
        page.wait_for_timeout(SETTLE_MS)
        go_home(page)
        check_state(report, page, tag)

    def from_sessions_page(page, tag):
        page.evaluate("CloudeWeb.openSessionsScreen()")
        page.wait_for_timeout(SETTLE_MS)
        go_home(page)
        check_state(report, page, tag)

    def menu_closes_over_home(page, tag):
        go_home(page)
        page.evaluate("CloudeWeb.openSettingsScreen()")
        page.wait_for_timeout(SETTLE_MS)
        page.keyboard.press("Escape")
        page.wait_for_timeout(SETTLE_MS)
        check_state(report, page, tag)

    def back_forward(page, tag):
        go_home(page)
        page.go_back()
        page.wait_for_timeout(SETTLE_MS)
        page.go_forward()
        page.wait_for_timeout(SETTLE_MS * 2)
        check_state(report, page, tag)

    def narrow_then_wide(page, tag):
        go_home(page)
        resize(page, NARROW)
        check_state(report, page, tag + " (narrow)")
        resize(page, WIDE)
        check_state(report, page, tag + " (wide again)")

    def resize_above(page, tag):
        go_home(page)
        resize(page, (1280, 800))
        check_state(report, page, tag)

    def entered_narrow(page, tag):
        resize(page, NARROW)
        go_home(page)
        resize(page, WIDE)
        check_state(report, page, tag, want_open=False)

    def drawer_toggle(page, tag):
        go_home(page)
        toggle_drawer(page, "session-widget-rail", RIGHT_KEY)
        check_state(report, page, tag + " (right closed)", want_open=True)
        toggle_drawer(page, "session-widget-rail", RIGHT_KEY)
        check_state(report, page, tag + " (right reopened)")

    def reload_on_home(page, tag):
        go_home(page)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector(".session-sidebar-row", timeout=20000)
        page.wait_for_timeout(SETTLE_MS * 3)
        check_state(report, page, tag)

    def deep_link(page, tag):
        go_home(page)
        page.goto(args.base + f"/session/carnivore_{SEED_NAME}", wait_until="domcontentloaded")
        page.wait_for_timeout(SETTLE_MS * 4)
        got = page.evaluate(MEASURE_JS)
        report.check(got["homeBox"] is None, f"{tag}: Home does not take over the deep-linked session", got["homeBox"])
        report.check(page.evaluate("App.currentScreen") == "terminal", f"{tag}: the deep-linked terminal is the screen", page.evaluate("App.currentScreen"))

    def click_during_restore(page, tag):
        go_home(page)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector(f'.session-sidebar-row[data-name$="_{OTHER_NAME}"]', timeout=20000)
        page.locator(f'.session-sidebar-row[data-name$="_{OTHER_NAME}"]').first.click(timeout=10000)
        page.wait_for_timeout(SETTLE_MS * 4)
        got = page.evaluate(MEASURE_JS)
        shown = page.evaluate("TerminalController._currentTmuxName ? TerminalController._currentTmuxName() : ''")
        report.check(got["homeBox"] is None, f"{tag}: Home does not land on the session the person clicked", got["homeBox"])
        report.check(shown.endswith(f"_{OTHER_NAME}"), f"{tag}: the clicked session is the one showing", shown)

    def unread_on_reload(page, tag):
        go_home(page)
        call(args, f"/sessions/carnivore_{SEED_NAME}/unread", "PATCH", {"unread": True})
        page.add_init_script(WS_LOG_JS)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector(".session-sidebar-row", timeout=20000)
        page.wait_for_timeout(SETTLE_MS * 3)
        check_state(report, page, tag)
        rows = call(args, "/sessions/list")
        items = rows if isinstance(rows, list) else rows.get("sessions", [])
        primary = page.evaluate("(window.__wsLog || []).filter((u) => u.includes('/ws/terminal') && !u.includes('observer=1'))")
        report.check(primary == [], f"{tag}: no primary terminal socket opened under Home", primary)
        flags = [r.get("unread") for r in items if f"_{SEED_NAME}" in str(r.get("tmux_session"))]
        report.check(bool(flags) and all(flags), f"{tag}: the restored session is still unread", flags)
        held = page.evaluate("!!(window.TerminalPrimaryHold && TerminalPrimaryHold.held())")
        report.check(held, f"{tag}: the primary socket is held closed while Home is up", held)
        call(args, f"/sessions/carnivore_{SEED_NAME}/unread", "PATCH", {"unread": False})
        page.locator(f'.session-sidebar-row[data-name$="_{SEED_NAME}"]').first.click(timeout=10000)
        page.wait_for_timeout(SETTLE_MS * 3)
        released = page.evaluate("!(window.TerminalPrimaryHold && TerminalPrimaryHold.held())")
        report.check(released, f"{tag}: leaving Home gives the primary socket back", released)
        primary = page.evaluate("(window.__wsLog || []).filter((u) => u.includes('/ws/terminal') && !u.includes('observer=1'))")
        report.check(primary != [], f"{tag}: the session the person opened connects normally", primary)

    case("home from the session", from_session)
    case("home from a menu page", from_menu)
    case("home from the sessions page", from_sessions_page)
    case("menu page closed over home", menu_closes_over_home)
    case("history back then forward", back_forward)
    case("window narrowed and widened", narrow_then_wide)
    case("window resized above 1024", resize_above)
    case("home entered narrow then widened", entered_narrow)
    case("right drawer closed and reopened", drawer_toggle)
    case("reload while on home", reload_on_home)
    case("deep link while on home", deep_link)
    case("click during the restore", click_during_restore)
    case("unread session survives a reload on home", unread_on_reload)


def run_all(args: argparse.Namespace, report: Report) -> None:
    original = call(args, "/preferences").get("values", {}).get("theme")
    seed_session(args, SEED_NAME)
    seed_session(args, OTHER_NAME)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for theme in [t for t in args.themes.split(",") if t]:
                set_theme(args, theme)
                scenarios(report, browser, args, theme)
        finally:
            browser.close()
            try:
                set_theme(args, original)
            except urllib.error.HTTPError as exc:
                print(f"NOTE: could not restore the theme ({exc.code})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True)
    parser.add_argument("--storage-state", required=True)
    parser.add_argument("--themes", default="carnivore,dracula")
    parser.add_argument("--shots", default=None)
    parser.add_argument("--only", default="", help="run only the states whose name contains this text")
    args = parser.parse_args()
    refused = refuse_live_target(args)
    if refused is not None:
        return refused
    report = Report()
    try:
        run_all(args, report)
    except (urllib.error.URLError, RuntimeError, OSError, PlaywrightError) as exc:
        print(f"CANNOT DETERMINE: {type(exc).__name__}: {exc}")
        return 2
    print("\n".join(report.lines))
    return report.exit_status()


if __name__ == "__main__":
    sys.exit(run_main(main))

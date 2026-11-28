"""The in-browser page-frame gate (page-frames plan, gate 4) and the S11 slide-out gate (#2775): drive real drawer pages and measure them.

Against ONE isolated validation server (a leased ``scripts/testsrv`` slot, never the live install; ``refuse_live_target``), under two
shipped themes with different accents (``frame_geometry.THEMES``), at a desktop window under a mouse and a phone under a thumb
(``frame_geometry.LAYOUTS``):

  1. every drawer page in ``MENU_PAGES`` is opened by its hash and its frame root measured: the header 37 / 56px, every base button in
     a frame region 26 / 44px (an icon button square), the nav frame's left bar 208px;
  2. at the desktop layout, every slide-out on the rail is opened: its title row and actions row buttons are the same 26px (Joe
     (ccsliinc), 2026-11-20, call C), and no title strip sits inside its body (slice S11).

The numbers and checks live in ``frame_geometry.py`` (no browser there, so each check is shown red on a planted measurement in
tests/python/design_system/test_frame_geometry.py). Exit codes: 0 every check met, 1 a violation (each printed as
``<layout>::<page>::<check>``), 2 COULD NOT DETERMINE: no Playwright, no browser for it (this gate never downloads one), a refused
target, a page that did not open, or nothing measured. A 2 is never a pass (gotcha 11).

Usage: python3 scripts/design/frame_geometry_run.py --base http://127.0.0.1:8101 --storage-state <slot auth json>
       CARNIVORE_GEOMETRY_CHROMIUM=<path to chrome-headless-shell> ... when the Playwright cache holds a different browser revision.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.design import frame_geometry as fg  # noqa: E402
from scripts.lib.verify_harness import (  # noqa: E402
    EXIT_CANNOT_DETERMINE, EXIT_FAIL, EXIT_PASS, call, refuse_live_target, run_main, set_theme,
)

OPEN_TIMEOUT_MS = 15000
SETTLE_MS = 600
RAIL_KEYS = "[data-rail-widget]"
SWARM_FLYOUT = "core.swarm"
CHROMIUM_ENV = "CARNIVORE_GEOMETRY_CHROMIUM"


def load_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    return sync_playwright


def measure_pages(browser: Any, args: argparse.Namespace, layout: fg.Layout, found: fg.Findings) -> None:
    ctx = browser.new_context(storage_state=args.storage_state, viewport={"width": layout.width, "height": layout.height},
                              has_touch=layout.touch, is_mobile=layout.touch)
    try:
        page = ctx.new_page()
        for entry in fg.menu_pages():
            if not fg.offered(entry, layout):
                continue
            page.goto(f"{args.base}/{entry.hash}", wait_until="domcontentloaded")
            try:
                page.wait_for_selector(f"#{entry.container} .oc-page[data-frame]", timeout=OPEN_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001
                raise fg.GeometryError(f"{entry.id} did not open in its frame at {layout.name}: {exc}") from exc
            page.wait_for_timeout(SETTLE_MS)
            found.rows.update(fg.check_page(entry.id, page.evaluate(fg.PAGE_PROBE, entry.container), layout))
            found.pages.add(f"{layout.name}::{entry.id}")
    finally:
        ctx.close()


def measure_flyouts(browser: Any, args: argparse.Namespace, found: fg.Findings) -> None:
    layout = fg.DESKTOP
    ctx = browser.new_context(storage_state=args.storage_state, viewport={"width": layout.width, "height": layout.height})
    try:
        page = ctx.new_page()
        page.goto(f"{args.base}/", wait_until="domcontentloaded")
        page.wait_for_selector(RAIL_KEYS, timeout=OPEN_TIMEOUT_MS)
        ids = page.eval_on_selector_all(RAIL_KEYS, "(keys) => keys.map((k) => k.dataset.railWidget)")
        if SWARM_FLYOUT not in ids:
            raise fg.GeometryError(f"the {SWARM_FLYOUT} slide-out is not on the rail (is the huddle plugin on in the slot?)")
        for flyout in ids:
            page.click(f'[data-rail-widget="{flyout}"]')
            page.wait_for_timeout(SETTLE_MS)
            answer = page.evaluate(fg.FLYOUT_PROBE, fg.TITLE_ROWS)
            if answer is None and flyout != SWARM_FLYOUT:
                continue
            found.rows.update(fg.check_flyout(answer, flyout, layout))
            found.flyouts.add(flyout)
            page.keyboard.press("Escape")
            page.wait_for_timeout(SETTLE_MS)
    finally:
        ctx.close()


def run(args: argparse.Namespace, sync_playwright: Any) -> fg.Findings:
    found = fg.Findings()
    with sync_playwright() as pw:
        try:
            executable = os.environ.get(CHROMIUM_ENV) or None
            browser = pw.chromium.launch(executable_path=executable) if executable else pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            raise fg.GeometryError(f"chromium could not launch (this gate never downloads a browser): {exc}") from exc
        try:
            original = call(args, "/preferences").get("values", {}).get("theme")
        except OSError:
            browser.close()
            raise
        try:
            for theme in fg.THEMES:
                set_theme(args, theme)
                for layout in fg.LAYOUTS:
                    measure_pages(browser, args, layout, found)
                measure_flyouts(browser, args, found)
        finally:
            browser.close()
            set_theme(args, original)
    return found


def verdict(found: fg.Findings) -> int:
    if not found.pages or SWARM_FLYOUT not in found.flyouts:
        print(f"CANNOT DETERMINE: measured {len(found.pages)} pages and {sorted(found.flyouts)} slide-outs")
        return EXIT_CANNOT_DETERMINE
    for row in sorted(found.rows):
        print(f"FAIL {row}")
    print(f"{'FAIL' if found.rows else 'PASS'}: {len(found.pages)} page layouts and {len(found.flyouts)} slide-outs measured, "
          f"{len(found.rows)} violations")
    return EXIT_FAIL if found.rows else EXIT_PASS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the leased slot's base URL")
    parser.add_argument("--storage-state", required=True, help="the slot's signed-in Playwright storage state")
    args = parser.parse_args(argv)
    refused = refuse_live_target(args)
    if refused is not None:
        return refused
    sync_playwright = load_playwright()
    if sync_playwright is None:
        print("CANNOT DETERMINE: playwright is not installed, so no page was measured. Not a pass.")
        return EXIT_CANNOT_DETERMINE
    try:
        found = run(args, sync_playwright)
    except (fg.GeometryError, OSError, RuntimeError) as exc:
        print(f"CANNOT DETERMINE: {type(exc).__name__}: {exc}")
        return EXIT_CANNOT_DETERMINE
    return verdict(found)


if __name__ == "__main__":
    sys.exit(run_main(main))

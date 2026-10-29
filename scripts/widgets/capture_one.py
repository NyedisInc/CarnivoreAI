"""Capture ONE widget draw to a PNG plus metadata, through the shared harness: the Widget Lab's capture button.

The whole-catalog runner (``capture.py``) answers "does every widget pass at every size". This is its single-draw sibling for
a person at the Widget Lab page (``docs/widget-lab.md``): one widget, in one host, at one size, under one theme and fixture,
optionally with a pasted JSON scenario laid over the fixture and optionally with the widget's own menu open. It reuses the
same page, the same fixture server, the same fit check and junk-text scan and the same stage screenshot as the catalog
runner (``harness.py``); nothing is drawn a second way.

  1. open the harness page for the draw (the page waits for the scenario when one is given, then draws, and with
     ``--state menu`` presses the widget's menu button and waits until the menu is open);
  2. read the page's own report: the fit findings, the fixture misses, the readable text, and whether the menu opened;
  3. shoot the bounded stage (plus the open menu's box when it spills outside, the menu being a top-layer popover);
  4. check the PNG is a complete file, then write ``<out>/<stem>.png`` and ``<out>/<stem>.json``.

The metadata names the widget, the source revision (git sha, and whether the tree had uncommitted changes), the host, the size
(name, px, window), the theme, the fixture (kind, scenario or not, sha256 of the plain-data routes drawn) and the state.

A missing widget, host, size or fixture, a scenario that does not check out, a scenario route the widget never asked
for, a fit or junk-text finding, a menu that would not open, or a PNG that is not whole is a FAILED capture: the metadata
says ``"ok": false`` with every reason, the exit status is 1, and nothing here ever reports a pass for it.

Usage:
  venv/bin/python3 -m scripts.widgets.capture_one --widget core.notes --host home --size m --theme carnivore
      [--fixture data|empty|stress] [--scenario-file FILE] [--state normal|menu] [--out DIR] [--no-build]

Output: one JSON line on stdout (the metadata). Exit 0: captured and clean. Exit 1: the capture failed (see ``failures``).
Exit 2: CANNOT DETERMINE (playwright, the build, the server or the page did not run), never a pass.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.widgets.harness import (CHROMIUM_ARGS, REPO, HarnessError, build_if_stale, catalog, junk_findings, open_widget,
                                     serve, shoot)

HOSTS = ("home", "terminal", "drawer", "popout")
FIXTURES = ("data", "empty", "stress")
STATES = ("normal", "menu")
SIDEBAR_WIDTHS = ("min", "default", "wide", "max")
SIDEBAR_AREAS = ("closed", "glance", "full")
SIDEBAR_DENSITIES = ("compact", "cozy", "detailed")
SIDEBAR_WINDOW = {"width": 1440, "height": 800}
DEFAULT_OUT = REPO / "build" / "widget-lab"
MENU_SELECTOR = '[role="menu"]:popover-open'
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_END = b"IEND\xaeB`\x82"
READABLE_TEXT_LIMIT = 2000


class CaptureFailed(Exception):
    pass


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="scripts.widgets.capture_one", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--widget", required=True, help="harness key, such as core.notes or core.analytics:vitals")
    ap.add_argument("--host", required=True, choices=HOSTS)
    ap.add_argument("--size", required=True, help="a published size name for the host, such as s, m, l, phone")
    ap.add_argument("--theme", required=True)
    ap.add_argument("--fixture", default="data", choices=FIXTURES)
    ap.add_argument("--scenario-file", type=Path, help="a JSON scenario laid over the fixture (never evaluated)")
    ap.add_argument("--state", default="normal", choices=STATES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--sidebar", action="store_true", help="draw the widget in the REAL left sidebar (host drawer) and shoot the sidebar, in the state below")
    ap.add_argument("--width", default="default", choices=SIDEBAR_WIDTHS, help="with --sidebar: the drawer's width")
    ap.add_argument("--folded", action="store_true", help="with --sidebar: the drawer folded to the mini rail")
    ap.add_argument("--area", default="full", choices=SIDEBAR_AREAS, help="with --sidebar: the widget area's state")
    ap.add_argument("--density", default="compact", choices=SIDEBAR_DENSITIES, help="with --sidebar: the row density")
    ap.add_argument("--no-build", action="store_true", help="reuse client/widget-harness-build/ even if it is out of date")
    return ap.parse_args(argv)


def source_revision() -> dict[str, Any]:
    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=30)
        return done.stdout.strip() if done.returncode == 0 else ""

    return {"sha": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--", "web/src", "src", "client"))}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    if not path.is_file() or path.stat().st_size == 0:
        raise CaptureFailed("the screenshot file was not written")
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE) or not data.endswith(PNG_END):
        raise CaptureFailed("the screenshot is not a complete png")
    width, height = struct.unpack(">II", data[16:24])
    if width < 1 or height < 1:
        raise CaptureFailed("the screenshot has no pixels")
    return width, height


def stem_for(args: argparse.Namespace) -> str:
    scenario = "-scenario" if args.scenario_file else ""
    sidebar = f"-sidebar-{args.width}-{'folded' if args.folded else 'open'}-{args.area}-{args.density}" if args.sidebar else ""
    return f"{args.widget.replace(':', '--')}-{args.host}-{args.size}{sidebar}-{args.theme}-{args.fixture}{scenario}-{args.state}"


def find_size(widgets: list[dict], widget: str, host: str, size: str) -> dict:
    entry = next((w for w in widgets if w["key"] == widget), None)
    if entry is None:
        raise CaptureFailed(f"no widget {widget} is published by the harness")
    zone = "home" if host == "popout" else host
    sizes = entry["sizes"].get(zone)
    if not sizes:
        raise CaptureFailed(f"{widget} publishes no sizes for the {host} host")
    found = next((s for s in sizes if s["name"] == size), None)
    if found is None:
        raise CaptureFailed(f"{widget} publishes no size {size} in the {host} host (it has {', '.join(s['name'] for s in sizes)})")
    if not entry["fixture"]:
        raise CaptureFailed(f"{widget} ships no fixture, so there is nothing true to draw it from")
    return found


def clip_box(page: Any, with_menu: bool) -> dict[str, float]:
    boxes = page.evaluate("""(menuSelector) => {
        const rect = (el) => { const r = el.getBoundingClientRect(); return [r.left + scrollX, r.top + scrollY, r.right + scrollX, r.bottom + scrollY]; };
        const out = [rect(document.querySelector('.wh-stage'))];
        const menu = document.querySelector(menuSelector);
        if (menu) out.push(rect(menu));
        return out;
    }""", MENU_SELECTOR)
    if with_menu and len(boxes) < 2:
        raise CaptureFailed("the menu was asked for but none is open to shoot")
    left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
    right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
    return {"x": max(left, 0), "y": max(top, 0), "width": right - max(left, 0), "height": bottom - max(top, 0)}


def draw_and_shoot(page: Any, base: str, args: argparse.Namespace, size: dict, png: Path, scenario: str | None) -> dict[str, Any]:
    sidebar = args.sidebar
    page.set_viewport_size(SIDEBAR_WINDOW if sidebar else {"width": size["viewport"], "height": 1100 if size["viewport"] > 500 else 844})
    first = {"zone": args.host, "size": args.size, "theme": args.theme}
    extra = {"state": "menu"} if args.state == "menu" else {}
    if sidebar:
        extra |= {"shell": "sidebar", "lab": "1", "width": args.width, "folded": "1" if args.folded else "0", "area": args.area, "density": args.density}
    opened = open_widget(page, base, args.widget, args.fixture, first, extra=extra or None, scenario=scenario)
    report = page.evaluate("() => window.__widgetHarness.result || null")
    png.parent.mkdir(parents=True, exist_ok=True)
    if report is not None and sidebar:
        clip = report.get("clip")
        if not clip:
            raise CaptureFailed("the real sidebar drew nothing to shoot")
        page.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": clip["w"], "height": clip["h"]}, animations="disabled")
    if report is None:
        return {"error": opened.error or "the page drew nothing", "findings": [], "misses": [], "text": "", "fixture_json": "{}", "unused_routes": [],
                "menu": {"asked": args.state == "menu", "open": False, "reason": ""}}
    if sidebar:
        pass
    elif report["menu"]["open"]:
        page.screenshot(path=str(png), clip=clip_box(page, True), full_page=True, animations="disabled")
    elif page.evaluate("() => !!document.querySelector('.wh-stage')"):
        shoot(page, png)
    return {"error": opened.error or report["error"], "findings": report["findings"], "misses": report["misses"],
            "text": report["text"], "fixture_json": report["fixtureJson"], "unused_routes": report["unusedScenarioRoutes"],
            "menu": report["menu"]}


def failures_of(draw: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if draw["error"]:
        reasons.append(draw["error"])
    reasons += [f"fit finding {f['rule']}: {f['detail']} ({f['selector']})" for f in draw["findings"] + junk_findings(draw["text"])]
    reasons += [f"the scenario names {route} but the widget never asked for it (a mistyped route?)" for route in draw["unused_routes"]]
    if draw["menu"]["asked"] and not draw["menu"]["open"] and draw["menu"]["reason"] not in draw["error"]:
        reasons.append(draw["menu"]["reason"] or "the menu did not open")
    return reasons


def capture(args: argparse.Namespace) -> dict[str, Any]:
    from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    scenario = args.scenario_file.read_text(encoding="utf-8") if args.scenario_file else None
    if not args.no_build:
        build_if_stale()
    httpd, base = serve()
    png = args.out / f"{stem_for(args)}.png"
    for stale in (png, png.with_suffix(".json")):
        stale.unlink(missing_ok=True)
    meta: dict[str, Any] = {"widget": args.widget, "host": args.host, "theme": args.theme, "state": args.state,
                            "size": {"name": args.size}, "source_revision": source_revision(),
                            "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                            "fixture": {"kind": args.fixture, "scenario": scenario is not None, "hash": ""}, "failures": []}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=CHROMIUM_ARGS)
            page = browser.new_page(device_scale_factor=1, reduced_motion="reduce", timezone_id="UTC", locale="en-US")
            try:
                widgets, _ = catalog(page, base)
                size = find_size(widgets, args.widget, args.host, args.size)
                meta["size"] = {"name": args.size, "w": size["w"], "h": size["h"], "viewport": size["viewport"]}
                draw = draw_and_shoot(page, base, args, size, png, scenario)
                meta["fixture"]["hash"] = sha256_text(draw["fixture_json"])
                meta["findings"], meta["misses"], meta["menu_open"] = draw["findings"], draw["misses"], draw["menu"]["open"]
                meta["text"] = draw["text"][:READABLE_TEXT_LIMIT]
                meta["failures"] = failures_of(draw)
            except CaptureFailed as exc:
                meta["failures"].append(str(exc))
            except PlaywrightError as exc:
                raise HarnessError(f"playwright: {type(exc).__name__}: {exc}") from exc
            finally:
                browser.close()
    finally:
        httpd.shutdown()
    try:
        meta["png"] = {"path": str(png), "pixels": list(png_size(png))}
    except CaptureFailed as exc:
        meta["png"] = {"path": str(png), "pixels": None}
        meta["failures"].append(str(exc))
    meta["ok"] = not meta["failures"]
    meta["metadata"] = str(png.with_suffix(".json"))
    png.parent.mkdir(parents=True, exist_ok=True)
    png.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main(argv: list[str]) -> int:
    args = parse(argv)
    if args.sidebar and args.host != "drawer":
        print("capture_one: --sidebar draws the left drawer, so --host must be drawer", file=sys.stderr)
        return 2
    try:
        import playwright  # noqa: F401, PLC0415
    except ImportError:
        print("capture_one: CANNOT DETERMINE - playwright is not installed in this venv", file=sys.stderr)
        return 2
    try:
        meta = capture(args)
    except HarnessError as exc:
        print(f"capture_one: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    print(json.dumps(meta))
    return 0 if meta["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

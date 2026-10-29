"""Capture and fit-check every widget from its fixture, at its standard sizes, under the capture themes.

One pipeline for two jobs (Joe (ccsliinc), 2026-10-01: "take the thinking out
of the loop"): the PNGs a widget's description shows, and the fit check that
gates a widget change. For every widget the harness publishes (every core
manifest and every analytics gallery preset), every zone it declares that
changes how it is drawn (home, terminal, drawer; the pop-out draws the home
host unchanged), every standard size (s, m, l, phone on the grids; the drawer's
widths and the glance row in the sidebar), every size the widget claims as
TESTED (``u<w>x<h>``: its ``fits.tested`` list, else the standard set 1 x 1 to
8 x 2 at or above its floor, the aspects the gear menu offers) and the
off-standard sizes a widget must fill though it suggests none of them (odd-wide, odd-tall, odd-mid), every
capture theme, and both fixtures (data, empty):

  1. draw it in the harness (frozen clock, fixture server, reduced motion,
     settled: no request and no DOM change for 600ms, animations finished);
  2. run the fit check in the page (overflow-x, overflow-y, scrollbar-x,
     clipped-text, overlap, bad-text, catalog-key) and collect fixture misses;
     any finding fails the run (Joe (ccsliinc), 2026-10-03: "if there is any
     slipping it fails");
  3. write ``<out>/<key>/<zone>-<size>-<fixture>-<theme>.png``.

Usage:
  venv/bin/python3 -m scripts.widgets.capture [--out DIR] [--only KEY ...]
      [--themes a,b] [--fixtures data,empty] [--zones home,...] [--sizes all | s,m,u,...]
      [--no-build] [--no-shots] [--catalog]

  --catalog also writes the description images: the data fixture under the
  default theme, home zone, one per size, to
  ``features/media/widgets/<key>/<size>.png`` (2x, pngquant when present).

A run with ``--only`` keeps the earlier draws of every OTHER widget in the
same ``--out`` (``renders.json``), so a long capture can run in slices and
still write one report.

Output: ``<out>/report.md`` (failures grouped by widget, worst first) and
``<out>/report.json``. Exit 0: every draw passed. Exit 1: at least one fit
finding, a draw error, or a widget with no fixture. Exit 2: CANNOT DETERMINE
(the harness did not build, serve or draw), never a pass.

Docs: ``docs/widget-spec.md``, "Fixtures, standard sizes and the fit check".
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from scripts.widgets import defect_allow
from scripts.widgets.catalog_meta import write_catalog_metadata
from scripts.widgets.fit_report import merge_previous, write_reports
from scripts.widgets.harness import (CHROMIUM_ARGS, REPO, HarnessError, Render, build_harness, catalog, defects, open_widget,
                                     serve, shoot, show)

CAPTURED_ZONES = ("home", "terminal", "drawer")
DEFAULT_OUT = REPO / "build" / "widget-capture"
CATALOG_MEDIA = REPO / "features" / "media" / "widgets"
OFF_SIZE_PREFIX = "odd-"
NAMED_SIZES_WORD = "named"


@dataclass(frozen=True)
class RunOptions:

    zones: str
    fixtures: str
    sizes: str
    no_shots: bool
    out: Path
    defects: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "RunOptions":
        return cls(zones=args.zones, fixtures=args.fixtures, sizes=args.sizes, no_shots=args.no_shots, out=args.out)


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="scripts.widgets.capture", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where shots and the report go")
    ap.add_argument("--only", nargs="*", default=[], help="widget keys or key prefixes (core.analytics:)")
    ap.add_argument("--themes", help="comma list; default: the harness's capture themes")
    ap.add_argument("--fixtures", default="data,empty")
    ap.add_argument("--zones", default=",".join(CAPTURED_ZONES))
    ap.add_argument("--sizes", default="all",
                    help="comma list of size names, 'named' for every named size the widget calls out, or 'all' (default)")
    ap.add_argument("--no-build", action="store_true", help="reuse client/widget-harness-build/")
    ap.add_argument("--no-shots", action="store_true", help="fit-check only, write no PNG")
    ap.add_argument("--catalog", action="store_true", help="also write features/media/widgets/<key>/<size>.png")
    return ap.parse_args(argv)


def selected(widgets: list[dict], only: list[str]) -> list[dict]:
    if not only:
        return widgets
    return [w for w in widgets if any(w["key"] == o or (o.endswith(":") and w["key"].startswith(o)) for o in only)]


def size_wanted(size: dict, sizes: str) -> bool:
    picked = sizes.split(",")
    return "all" in picked or size["name"] in picked or (bool(size.get("declared")) and NAMED_SIZES_WORD in picked)


def layout_defect_findings(page, render: Render, allowed: list[defect_allow.Allowance]) -> list[dict]:
    draw = {"key": render.key, "size": render.size, "theme": render.theme, "shape": render.fixture}
    return [{k: f[k] for k in ("rule", "selector", "px", "detail")} for f in defects(page)["findings"]
            if f["severity"] == "fail" and not any(e.allows(draw, f) for e in allowed)]


def run_widget(page, base: str, widget: dict, options: RunOptions, themes: list[str]) -> list[Render]:
    renders: list[Render] = []
    allowed = defect_allow.load() if options.defects else []
    zones = [z for z in widget["zones"] if z in options.zones.split(",")]
    for fixture in options.fixtures.split(","):
        first = True
        for zone in zones:
            for size in widget["sizes"][zone]:
                if not size_wanted(size, options.sizes):
                    continue
                page.set_viewport_size({"width": size["viewport"], "height": 1100 if size["viewport"] > 500 else 844})
                for theme in themes:
                    if first:
                        loaded = open_widget(page, base, widget["key"], fixture,
                                             {"zone": zone, "size": size["name"], "theme": theme})
                        if loaded.error:
                            renders.append(loaded)
                            return renders
                        first = False
                    render = show(page, widget["key"], fixture, zone, size["name"], theme)
                    if options.defects and not render.error:
                        render.findings += layout_defect_findings(page, render, allowed)
                    if not options.no_shots and not render.error:
                        render.shot = shoot(page, options.out / widget["key"] / f"{zone}-{size['name']}-{fixture}-{theme}.png")
                    renders.append(render)
    return renders


def write_catalog_images(browser, base: str, widgets: list[dict], theme: str) -> int:
    written = 0
    page = browser.new_page(device_scale_factor=2, reduced_motion="reduce", timezone_id="UTC", locale="en-US")
    for widget in widgets:
        if "home" not in widget["zones"]:
            continue
        loaded = False
        for size in widget["sizes"]["home"]:
            if size["name"].startswith(OFF_SIZE_PREFIX) or size.get("declared"):
                continue
            page.set_viewport_size({"width": size["viewport"], "height": 1100 if size["viewport"] > 500 else 844})
            if not loaded:
                open_widget(page, base, widget["key"], "data", {"zone": "home", "size": size["name"], "theme": theme})
                loaded = True
            if show(page, widget["key"], "data", "home", size["name"], theme).error:
                continue
            dest = shoot(page, CATALOG_MEDIA / widget["key"].replace(":", "--") / f"{size['name']}.png")
            if shutil.which("pngquant"):
                subprocess.run(["pngquant", "--force", "--skip-if-larger", "--ext", ".png", "--strip", str(dest)],
                               capture_output=True, timeout=60)
            written += 1
        write_catalog_metadata(CATALOG_MEDIA / widget["key"].replace(":", "--"), widget["key"], theme)
    page.close()
    return written


def main(argv: list[str]) -> int:
    args = parse(argv)
    options = RunOptions.from_args(args)
    started = time.monotonic()
    try:
        from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        print("capture: CANNOT DETERMINE - playwright is not installed in this venv", file=sys.stderr)
        return 2
    try:
        if not args.no_build:
            build_harness()
        httpd, base = serve()
    except HarnessError as exc:
        print(f"capture: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    renders: list[Render] = []
    missing: list[str] = []
    widgets: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=CHROMIUM_ARGS)
            page = browser.new_page(device_scale_factor=1, reduced_motion="reduce", timezone_id="UTC", locale="en-US")
            widgets, harness_themes = catalog(page, base)
            themes = args.themes.split(",") if args.themes else harness_themes
            chosen = selected(widgets, args.only)
            if not chosen:
                raise HarnessError(f"no widget matches {args.only}")
            missing = [w["key"] for w in chosen if not w["fixture"]]
            for widget in chosen:
                one = run_widget(page, base, widget, options, themes)
                bad = sum(1 for r in one if r.findings or r.error)
                print(f"capture: {widget['key']}: {len(one)} draws, {bad} failing", flush=True)
                renders.extend(one)
            if args.catalog:
                print(f"capture: wrote {write_catalog_images(browser, base, chosen, harness_themes[0])} catalog images")
            browser.close()
    except (HarnessError, PlaywrightError) as exc:
        print(f"capture: CANNOT DETERMINE - {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        httpd.shutdown()
    if not renders:
        print("capture: CANNOT DETERMINE - nothing was drawn", file=sys.stderr)
        return 2
    elapsed = time.monotonic() - started
    if args.only:
        renders = merge_previous(args.out, renders)
        drawn = {r.key for r in renders}
        missing = [w["key"] for w in widgets if not w["fixture"] and w["key"] in drawn]
    report = write_reports(args.out, renders, missing, elapsed)
    failing = sum(1 for r in renders if r.findings or r.error)
    print(f"capture: {len(renders)} draws in {elapsed:.0f}s, {failing} failing, "
          f"{len(missing)} widgets without a fixture; report {report}")
    (args.out / "summary.json").write_text(json.dumps({"draws": len(renders), "failing": failing,
                                                        "missing_fixtures": missing, "seconds": round(elapsed)}) + "\n")
    return 1 if failing or missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

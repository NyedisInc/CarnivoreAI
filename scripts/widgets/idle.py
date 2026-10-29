"""The idle-traffic check over the Widget Lab harness: what each widget costs the network when nobody is looking (PLAN 8.10).

The harness page (``web/src/widget-harness/idle-run.ts``) hands every timer the draw left running to a virtual clock and measures a
settle minute, then a SHOWN minute and a HIDDEN minute, counting only the widget's own requests (the shell's reads are named
``isShellRoute`` and left out). A hidden minute must be zero. ``--plant`` adds a hidden 5 second ``setInterval`` fetch to the page
first, the negative control: it must read 12 or 13 and fail.

Usage:
  venv/bin/python3 -m scripts.widgets.idle [--only KEY ...] [--fixture data|empty] [--plant] [--no-build] [--out FILE]

Output: one line per widget and, with ``--out``, a JSON list of ``{key, shown, hidden, shell, hiddenRoutes}``.
Exit 0: every selected widget sent nothing hidden. Exit 1: at least one did. Exit 2: CANNOT DETERMINE, never a pass.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.widgets.capture import selected
from scripts.widgets.harness import CHROMIUM_ARGS, HarnessError, build_if_stale, catalog, open_widget, serve

PLANTED_POLL = "() => { setInterval(() => fetch('/api/v1/planted-offender'), 5000); }"

FIRST_DRAW = {"zone": "home", "size": "m", "theme": "carnivore"}


def idle_of(page: Any, base: str, key: str, fixture: str = "data", plant: bool = False) -> dict:
    drawn = open_widget(page, base, key, fixture, FIRST_DRAW, extra={"idle": "1"})
    if drawn.error:
        raise HarnessError(f"{key} did not draw: {drawn.error}")
    if plant:
        page.evaluate(PLANTED_POLL)
    try:
        answer = page.evaluate("() => window.__widgetHarness.idle()")
    except Exception as exc:
        raise HarnessError(f"{key}: the idle check failed: {str(exc).splitlines()[0]}") from None
    return {"key": key, **answer}


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="scripts.widgets.idle", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=[], help="widget keys or key prefixes")
    ap.add_argument("--fixture", default="data", choices=("data", "empty"))
    ap.add_argument("--plant", action="store_true", help="negative control: plant a hidden 5 s poll")
    ap.add_argument("--no-build", action="store_true", help="reuse client/widget-harness-build/")
    ap.add_argument("--out", type=Path, help="write the JSON list here")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse(argv)
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        print("idle: CANNOT DETERMINE - playwright is not installed in this venv", file=sys.stderr)
        return 2
    results: list[dict] = []
    try:
        if not args.no_build:
            build_if_stale()
        httpd, base = serve()
    except HarnessError as exc:
        print(f"idle: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=CHROMIUM_ARGS)
            page = browser.new_page(reduced_motion="reduce", timezone_id="UTC", locale="en-US")
            widgets, _themes = catalog(page, base)
            chosen = [w for w in selected(widgets, args.only) if w["fixture"]]
            if not chosen:
                raise HarnessError(f"no widget with a fixture matches {args.only}")
            for widget in chosen:
                one = idle_of(page, base, widget["key"], args.fixture, args.plant)
                results.append(one)
                print(f"idle: {one['key']}: shown {one['shown']['requests']}, hidden {one['hidden']['requests']}, shell {one['shell']}", flush=True)
            browser.close()
    except HarnessError as exc:
        print(f"idle: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    finally:
        httpd.shutdown()
    if args.out:
        args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    loud = [r for r in results if r["hidden"]["requests"] > 0]
    print(f"idle: {len(results)} widgets, {len(loud)} with hidden traffic")
    return 1 if loud else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

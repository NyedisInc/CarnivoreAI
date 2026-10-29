"""The widget gate: run a widget's contract record through the Widget Lab harness and say pass or fail (issue #1944).

For every widget record in ``src/data/widget-contracts.json`` (``docs/extension-contract.md`` section 9) this draws the
widget's fixture scenarios (data and empty) in EVERY host the record declares (home, terminal, drawer; the pop-out is the
home host in its own window and the glance row is the drawer's mini size), at EVERY size the record calls out, under at
least two themes (all capture themes by default), runs the fit check and the junk-text scan on each draw, and writes one
GATE RECORD per widget (``src/cplugs/sdk/widget_gate.py``, format version 1) that a submission path judges with
``refuse_unless_passing``. It uses the harness functions of ``scripts/widgets/harness.py``, the same page, fixture server
and checks as ``scripts/widgets/capture.py`` and the Widget Lab plugin; no second implementation of any check.

A widget FAILS on any fit or junk-text finding, a draw error, a declared size or host the harness does not publish, or a
fixture it does not ship. Fixture misses are reported, not failed on (the app-wide routes every page asks). A record with no ``remembers`` declaration
only WARNS (``warnings`` in the gate record).

Usage:
  venv/bin/python3 -m scripts.widgets.gate [--only ID ...] [--themes a,b] [--out DIR] [--no-build] [--records FILE]
      [--sizes named | all]

Output: ``<out>/<id>.gate.json`` per widget and ``<out>/summary.json``. Exit 0: every selected widget passed. Exit 1: at
least one failed. Exit 2: CANNOT DETERMINE (the harness did not build, serve or draw, or no widget matched), never a pass.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from scripts.widgets.capture import run_widget, write_catalog_images
from scripts.widgets.fit_table import read_gates, write_table
from scripts.widgets.verdicts import cells_of, render_failures
from scripts.widgets.capture_one import source_revision
from scripts.widgets.harness import CHROMIUM_ARGS, REPO, HarnessError, Render, build_if_stale, catalog, serve
from src.cplugs.sdk.widget_decl import REQUIRED_FIXTURES, ZONE_HOSTS, problems_in
from src.cplugs.sdk.widget_gate import GATE_SCHEMA, MIN_THEMES, record_digest

RECORDS_PATH = REPO / "src" / "data" / "widget-contracts.json"
DEFAULT_OUT = REPO / "build" / "widget-gate"
# pop-out window
POPOUT_HOST, GLANCE_HOST, GLANCE_SIZE = "popout", "glance", "glance"
DRAWER_SIZES = "s,m,l"


def load_records(path: Path = RECORDS_PATH) -> list[dict]:
    """The widget contract records in ``path``. Raises: HarnessError when the file is unreadable (the run cannot determine)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))["widgets"]
    except (OSError, ValueError, KeyError) as exc:
        raise HarnessError(f"cannot read the widget records {path}: {type(exc).__name__}") from exc


def _wanted_sizes(record: Mapping[str, Any], zone: str, mode: str) -> str:
    if mode == "all":
        return "all"
    if zone == "drawer":
        return DRAWER_SIZES + ("," + GLANCE_SIZE if GLANCE_HOST in record["hosts"] else "")
    return "named"


def warnings_in(record: Mapping[str, Any]) -> list[str]:
    if "remembers" in record:
        return []
    return [f"{record['id']}: declares no remembers list (view state kept across a refresh; [] means stateless)"]


def gate_widget(page: Any, base: str, record: Mapping[str, Any], published: list[dict], themes: list[str],
                sizes_mode: str = "named", keys: list[str] | None = None) -> dict:
    failures: list[str] = [f"record: {p}" for p in problems_in(record)]
    mine = [w for w in published if w["manifest"] == record["id"] and (keys is None or w["key"] in keys)]
    renders: list[Render] = []
    if not mine:
        failures.append("the harness draws no widget with this id")
    if len(themes) < MIN_THEMES:
        failures.append(f"only {len(themes)} theme(s) to draw under, at least {MIN_THEMES} are required")
    for gone in (n for n in REQUIRED_FIXTURES if n not in record["fixtures"]):
        failures.append(f"no {gone} fixture is shipped")
    for widget in mine:
        if not widget["fixture"]:
            failures.append(f"{widget['key']}: ships no fixture")
    runnable = [w for w in mine if w["fixture"]] if not failures else []
    for widget in runnable:
        zones = [z for z in ZONE_HOSTS if z in record["hosts"] and z in widget["zones"]]
        for zone in zones:
            args = SimpleNamespace(zones=zone, fixtures=",".join(REQUIRED_FIXTURES), sizes=_wanted_sizes(record, zone, sizes_mode),
                                   no_shots=True, out=DEFAULT_OUT, defects=True)
            renders += run_widget(page, base, widget, args, themes)
    return _gate_record(record, runnable, renders, themes, failures, sizes_mode)


def _gate_record(record: Mapping[str, Any], widgets: list[dict], renders: list[Render], themes: list[str],
                 failures: list[str], sizes_mode: str) -> dict:
    drawn = [r for r in renders if not r.error]
    for r in renders:
        failures += render_failures(r)
    covered_zones = {r.zone for r in drawn}
    hosts = sorted(covered_zones | ({POPOUT_HOST} if "home" in covered_zones else set())
                   | ({GLANCE_HOST} if any(r.zone == "drawer" and r.size == GLANCE_SIZE for r in drawn) else set()))
    published_sizes = {s["name"] for w in widgets for z in w["sizes"].values() for s in z if s.get("declared")}
    for size in record["sizes"]:
        if size not in published_sizes and widgets:
            failures.append(f"declared size {size} is not published by the harness")
    sizes = sorted({r.size for r in drawn} & set(record["sizes"]))
    for host in (h for h in record["hosts"] if h not in hosts):
        failures.append(f"declared host {host} was never drawn")
    failures = list(dict.fromkeys(failures))
    return {"schema": GATE_SCHEMA, "widget": record["id"], "record_sha256": record_digest(record), "ok": not failures,
            "determined": True, "themes": sorted({r.theme for r in drawn}), "hosts": hosts, "sizes": sizes,
            "fixtures": sorted({r.fixture for r in drawn}), "draws": len(renders),
            "findings": sum(len(r.findings) for r in renders), "errors": sum(1 for r in renders if r.error or r.console),
            "misses": sorted({m for r in renders for m in r.misses}), "failures": failures, "warnings": warnings_in(record),
            "sizes_mode": sizes_mode, "cells": cells_of(renders, record["hosts"]), "source_revision": source_revision(),
            "ran_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="scripts.widgets.gate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=[], help="widget ids (core.notes)")
    ap.add_argument("--themes", help="comma list; default: the harness's capture themes (at least two)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--records", type=Path, default=RECORDS_PATH)
    ap.add_argument("--keys", nargs="*", help="gate only these harness keys of the --only widgets (a slice of a family; its records are partial)")
    ap.add_argument("--sizes", choices=("named", "all"), default="named")
    ap.add_argument("--catalog", action="store_true",
                    help="after the gate, write the catalog images and metadata (features/media/widgets) for every widget that PASSED")
    ap.add_argument("--no-build", action="store_true", help="skip the build even when the harness page is stale")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    """Build if stale, serve, gate each selected widget, write the gate records. Output: the exit code (0 pass, 1 fail, 2 cannot determine)."""
    args = parse(argv)
    started = time.monotonic()
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        print("gate: CANNOT DETERMINE - playwright is not installed in this venv", file=sys.stderr)
        return 2
    try:
        records = load_records(args.records)
        chosen = [r for r in records if not args.only or r["id"] in args.only]
        if not chosen:
            raise HarnessError(f"no widget record matches {args.only}")
        if not args.no_build:
            build_if_stale()
        httpd, base = serve()
    except HarnessError as exc:
        print(f"gate: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    results: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=CHROMIUM_ARGS)
            page = browser.new_page(device_scale_factor=1, reduced_motion="reduce", timezone_id="UTC", locale="en-US")
            published, harness_themes = catalog(page, base)
            themes = args.themes.split(",") if args.themes else harness_themes
            args.out.mkdir(parents=True, exist_ok=True)
            for record in chosen:
                gate = gate_widget(page, base, record, published, themes, args.sizes, args.keys)
                (args.out / f"{record['id']}.gate.json").write_text(json.dumps(gate, indent=1) + "\n", encoding="utf-8")
                results.append(gate)
                print(f"gate: {record['id']}: {'PASS' if gate['ok'] else 'FAIL'} ({gate['draws']} draws, {len(gate['failures'])} failures)", flush=True)
                for warning in gate["warnings"]:
                    print(f"gate: warning: {warning}", flush=True)
            write_table(args.out, read_gates(args.out), source_revision())
            if args.catalog:
                passed = {g["widget"] for g in results if g["ok"]}
                skipped = sorted({g["widget"] for g in results} - passed)
                chosen_keys = [w for w in published if w["manifest"] in passed]
                print(f"gate: wrote {write_catalog_images(browser, base, chosen_keys, harness_themes[0])} catalog images"
                      + (f"; none for the failing {', '.join(skipped)}" if skipped else ""))
            browser.close()
    except HarnessError as exc:
        print(f"gate: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    finally:
        httpd.shutdown()
    failing = [g["widget"] for g in results if not g["ok"]]
    (args.out / "summary.json").write_text(json.dumps({"passed": [g["widget"] for g in results if g["ok"]], "failed": failing,
                                                        "seconds": round(time.monotonic() - started)}, indent=1) + "\n", encoding="utf-8")
    print(f"gate: {len(results) - len(failing)} passed, {len(failing)} failed in {time.monotonic() - started:.0f}s; records in {args.out}")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

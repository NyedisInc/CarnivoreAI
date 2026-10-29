"""Sweep every widget for layout defects: every named size, three data shapes, three themes.

Joe (ccsliinc), Task Manager item 51, 2026-10-07: "we are not doing a good job of
looking for unreadable or overlapping sizes. id like to try to do it in
testing." The fit check (``scripts/widgets/capture.py``) asks whether a widget
stays in its box; this asks whether what is in the box can be read. Same
harness, same fixtures, same themes; the detector is
``web/src/widget-harness/layout-defects.ts`` (overlap, clipped, ellipsis,
escape, tiny-text, low-contrast, wrap, no-text).

For every widget the harness publishes (every core manifest and every
analytics gallery preset), every NAMED size it calls out (``fits.sizes``) on
the home grid, every data shape (data, empty, stress: ``fixtures/stress.ts``)
and every capture theme: draw it, run the detector, and shoot the stage when
a FAILING finding shows. Failing findings are then sorted by the allow-list
(``scripts/widgets/defect_allow.py``): an allowed one is reported, an
unallowed one or a stale allowance fails the run.

Usage:
  venv/bin/python3 -m scripts.widgets.defects [--only KEY ...] [--themes a,b]
      [--shapes data,empty,stress] [--out DIR] [--report PATH] [--no-build]

``--only`` keeps the earlier draws of every other widget in the same ``--out``
(``draws.json``), so a long sweep can run in slices and still write one report.

Exit 0: no unallowed failing finding and no stale allowance. Exit 1: at least
one. Exit 2: CANNOT DETERMINE (the harness did not build, serve or draw).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from scripts.widgets import defect_allow
from scripts.widgets.harness import (CHROMIUM_ARGS, REPO, HarnessError, build_harness, catalog, defects, open_widget,
                                     serve, shoot, show)

SHAPES = ("data", "empty", "stress")
ZONE = "home"
DEFAULT_OUT = REPO / "build" / "widget-defects"


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="scripts.widgets.defects", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where shots, draws.json and report.md go")
    ap.add_argument("--report", type=Path, help="also copy the report here")
    ap.add_argument("--only", nargs="*", default=[], help="widget keys or key prefixes ending in ':'")
    ap.add_argument("--themes", help="comma list; default: the harness's capture themes")
    ap.add_argument("--shapes", default=",".join(SHAPES))
    ap.add_argument("--viewport", choices=("page", "box"), default="page",
                    help="page: the size's own page width (default); box: a window the size of the box, as the "
                         "widgets page's preview frame draws it (below 1024px the app hands a cell its phone budget)")
    ap.add_argument("--no-build", action="store_true", help="reuse client/widget-harness-build/")
    return ap.parse_args(argv)


def wanted(key: str, only: list[str]) -> bool:
    return not only or any(key == o or (o.endswith(":") and key.startswith(o)) for o in only)


STAGE_MARGIN_PX = 16


def viewport_for(size: dict, mode: str) -> dict:
    if mode == "box" and size.get("h"):
        return {"width": size["w"] + 2 * STAGE_MARGIN_PX, "height": size["h"] + 2 * STAGE_MARGIN_PX}
    return {"width": size["viewport"], "height": 1100 if size["viewport"] > 500 else 844}


def sweep_widget(page, base: str, widget: dict, themes: list[str], shapes: list[str], out: Path,
                 viewport: str = "page") -> list[dict]:
    draws: list[dict] = []
    sizes = [s for s in widget["sizes"].get(ZONE, []) if s.get("declared")]
    for shape in shapes:
        loaded = False
        for size in sizes:
            page.set_viewport_size(viewport_for(size, viewport))
            for theme in themes:
                draw = {"key": widget["key"], "size": size["name"], "theme": theme, "shape": shape, "viewport": viewport,
                        "findings": [], "checked": {}, "error": "", "shot": None}
                if not loaded:
                    first = open_widget(page, base, widget["key"], shape, {"zone": ZONE, "size": size["name"], "theme": theme})
                    loaded = True
                    if first.error:
                        draws.append({**draw, "error": first.error})
                        return draws
                try:
                    render = show(page, widget["key"], shape, ZONE, size["name"], theme)
                    report = defects(page) if not render.error else None
                except PlaywrightError as exc:
                    draws.append({**draw, "error": str(exc).splitlines()[0]})
                    return draws
                if render.error:
                    draws.append({**draw, "error": render.error})
                    continue
                draw.update(findings=report["findings"], checked=report["checked"])
                if any(f["severity"] == "fail" for f in report["findings"]):
                    name = f"{widget['key'].replace(':', '--')}/{size['name']}-{shape}-{theme}-{viewport}.png"
                    draw["shot"] = str(shoot(page, out / "shots" / name))
                draws.append(draw)
    return draws


def merge_previous(out: Path, draws: list[dict]) -> list[dict]:
    store = out / "draws.json"
    drawn = {d["key"] for d in draws}
    kept = json.loads(store.read_text(encoding="utf-8")) if store.is_file() else []
    return [d for d in kept if d["key"] not in drawn] + draws


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def write_report(out: Path, draws: list[dict], verdict: defect_allow.Verdict, seconds: float) -> Path:
    fails = Counter(f["rule"] for d in draws for f in d["findings"] if f["severity"] == "fail")
    warns = Counter(f["rule"] for d in draws for f in d["findings"] if f["severity"] == "warn")
    todo = sorted({e for _, _, e in verdict.allowed if e.todo}, key=lambda e: (e.widget, e.size, e.rule))
    lines = [
        "# Widget layout defects", "",
        f"{len(draws)} draws ({len({d['key'] for d in draws})} widgets, named sizes, home grid) in {seconds:.0f}s. "
        f"Failing, unallowed: **{len(verdict.failing)}**. Allowed: {len(verdict.allowed)} "
        f"({len(todo)} todo entries). Stale allowances: **{len(verdict.stale)}**. "
        f"Draw errors: {sum(1 for d in draws if d['error'])}.", "",
        "## Failing findings by detector (before the allow-list)", "",
        "| Detector | Failing | Warnings |", "|---|---|---|",
        *[f"| {rule} | {fails.get(rule, 0)} | {warns.get(rule, 0)} |" for rule in sorted(set(fails) | set(warns))], "",
    ]
    rows = [(d, f, "") for d, f in verdict.failing] + [(d, f, ("todo: " if e.todo else "allowed: ") + e.reason)
                                                     for d, f, e in verdict.allowed]
    lines += ["## Every failing finding", "",
              "| Widget | Size | Theme | Shape | Detector | Detail | Allow-list | Screenshot |", "|---|---|---|---|---|---|---|---|"]
    for d, f, why in sorted(rows, key=lambda r: (r[0]["key"], r[0]["size"], r[1]["rule"], r[0]["shape"], r[0]["theme"])):
        lines.append(f"| {d['key']} | {d['size']} | {d['theme']} | {d['shape']} | {f['rule']} | "
                     f"{_cell(f['detail'])} | {_cell(why) or 'NOT ALLOWED'} | {d['shot'] or ''} |")
    if verdict.stale:
        lines += ["", "## Stale allowances (match nothing: delete them)", ""]
        lines += [f"- {e.widget} {e.size} {e.rule} ({e.theme}/{e.shape}): {e.reason}" for e in verdict.stale]
    errors = [d for d in draws if d["error"]]
    if errors:
        lines += ["", "## Draw errors", ""] + [f"- {d['key']} {d['size']} {d['shape']}: {d['error']}" for d in errors]
    warned: Counter = Counter()
    example: dict[tuple, str] = {}
    for d in draws:
        for f in d["findings"]:
            if f["severity"] == "warn":
                warned[(d["key"], d["size"], f["rule"])] += 1
                example.setdefault((d["key"], d["size"], f["rule"]), f["detail"][:90])
    lines += ["", "## Warnings (reported, never failing), per widget, size and rule", "",
              "| Widget | Size | Rule | Findings | One of them |", "|---|---|---|---|---|"]
    lines += [f"| {k} | {sz} | {r} | {n} | {_cell(example[(k, sz, r)])} |" for (k, sz, r), n in sorted(warned.items())]
    lines += ["", "## Todo debt (allowed now, to fix)", ""]
    lines += [f"- {e.widget} {e.size} {e.rule}: {e.reason}" for e in todo] or ["- none"]
    report = out / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main(argv: list[str]) -> int:
    args = parse(argv)
    started = time.monotonic()
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    try:
        entries = defect_allow.load()
        if not args.no_build:
            build_harness()
        httpd, base = serve()
    except (HarnessError, defect_allow.AllowListError) as exc:
        print(f"defects: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    draws: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=CHROMIUM_ARGS)
            page = browser.new_page(device_scale_factor=1, reduced_motion="reduce", timezone_id="UTC", locale="en-US")
            widgets, harness_themes = catalog(page, base)
            themes = args.themes.split(",") if args.themes else list(harness_themes)
            chosen = [w for w in widgets if wanted(w["key"], args.only)]
            if not chosen:
                raise HarnessError(f"no widget matches {args.only}")
            for widget in chosen:
                one = sweep_widget(page, base, widget, themes, args.shapes.split(","), args.out, args.viewport)
                bad = sum(1 for d in one if d["error"] or any(f["severity"] == "fail" for f in d["findings"]))
                print(f"defects: {widget['key']}: {len(one)} draws, {bad} with a failing finding", flush=True)
                draws.extend(one)
            browser.close()
            judge_stale = themes == list(harness_themes) and args.shapes.split(",") == list(SHAPES)
    except HarnessError as exc:
        print(f"defects: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    finally:
        httpd.shutdown()
    if not draws:
        print("defects: CANNOT DETERMINE - nothing was drawn", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    if args.only:
        draws = merge_previous(args.out, draws)
    (args.out / "draws.json").write_text(json.dumps(draws, indent=1) + "\n", encoding="utf-8")
    verdict = defect_allow.apply(draws, entries, judge_stale=judge_stale)
    report = write_report(args.out, draws, verdict, time.monotonic() - started)
    if args.report:
        args.report.write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
    errors = sum(1 for d in draws if d["error"])
    print(f"defects: {len(draws)} draws, {len(verdict.failing)} unallowed failing, {len(verdict.allowed)} allowed, "
          f"{len(verdict.stale)} stale, {errors} draw errors; report {report}")
    return 1 if verdict.failing or verdict.stale or errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

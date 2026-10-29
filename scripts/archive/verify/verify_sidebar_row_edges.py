#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_csp_static_server import serve  # noqa: E402
from lib_pixel_measure import sample_pixel  # noqa: E402
import lib_sidebar_edge_checks as C  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HARNESS = "/tests/manual/sidebar-row-edges-harness.html"

VIEWPORT = {"width": 1280, "height": 900}

THEMES = ("terminal", "codex")

ROWS = (
    ("row-plain", "plain"),
    ("row-pinned", "pinned"),
    ("row-active", "active (current session)"),
    ("row-themed", "session-themed"),
    ("row-pinned-themed", "pinned + session-themed"),
)
CONTROL = ("control-rail", "CONTROL: 3px rail on purpose")

BORDER_OFFSET = 0
BAND_OFFSETS = (1, 2, 3)

SAME_TOL = 6
DIFF_TOL = 20

assert (BORDER_OFFSET, BAND_OFFSETS, SAME_TOL, DIFF_TOL) == (
    C.BORDER_OFFSET, C.BAND_OFFSETS, C.SAME_TOL, C.DIFF_TOL), (
    "sampling constants disagree between verify_sidebar_row_edges.py and "
    "lib_sidebar_edge_checks.py; every verdict would be measured at one "
    "depth and judged at another")


def settle(page, ids: list) -> None:
    ok = page.evaluate(
        """async (ids) => {
            const snap = () => ids.map((id) => {
                const el = document.getElementById(id);
                if (!el) return 'MISSING:' + id;
                const cs = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return [cs.borderLeftColor, cs.borderLeftWidth, cs.boxShadow,
                        cs.backgroundColor, cs.backgroundImage,
                        Math.round(r.left), Math.round(r.top),
                        Math.round(r.width), Math.round(r.height)].join('|');
            }).join(';;');
            const frame = () => new Promise((r) => requestAnimationFrame(() => r()));
            let prev = snap();
            for (let i = 0; i < 90; i++) {
                await frame();
                const now = snap();
                if (now === prev) { await frame(); if (snap() === now) return true; }
                prev = now;
            }
            return false;
        }""",
        ids,
    )
    if not ok:
        raise RuntimeError(
            "row paint never stopped changing across 90 animation frames, so no "
            "pixel sampled here would be the settled one"
        )


def sample_row(page, meta: dict) -> dict:
    r = meta["rect"]
    mid_y = r["y"] + r["h"] // 2
    left, right = {}, {}
    for off in (BORDER_OFFSET,) + BAND_OFFSETS:
        left[off] = sample_pixel(page, r["x"] + off, mid_y)[:3]
        right[off] = sample_pixel(page, r["x"] + r["w"] - 1 - off, mid_y)[:3]
    top = sample_pixel(page, r["x"] + r["w"] // 2, r["y"] + BORDER_OFFSET)[:3]
    return {"left": left, "right": right, "top": top, "rect": r,
            "boxShadow": meta["boxShadow"]}


def measure_theme(page, theme: str, undetermined: list):
    try:
        page.evaluate("t => window.__applyTheme(t)", theme)
    except Exception as exc:  # noqa: BLE001
        undetermined.append("%s: theme manifest would not apply: %s" % (theme, exc))
        return None
    ids = [rid for rid, _ in ROWS] + [CONTROL[0]]
    try:
        settle(page, ids)
    except RuntimeError as exc:
        undetermined.append("%s: %s" % (theme, exc))
        return None
    env = page.evaluate("() => window.__edges()")
    if env["hidden"] or env["visibilityState"] != "visible":
        undetermined.append(
            "%s: the tab reports itself hidden (%s), where transitions freeze at "
            "frame zero and no sampled pixel means anything"
            % (theme, env["visibilityState"]))
        return None
    if env["innerWidth"] != VIEWPORT["width"]:
        undetermined.append(
            "%s: the PAGE reports innerWidth %s but the viewport was asked for %s - "
            "never trust a sizing tool's own success string"
            % (theme, env["innerWidth"], VIEWPORT["width"]))
        return None
    rows = {}
    for rid, label in ROWS + (CONTROL,):
        meta = page.evaluate("id => window.__row(id)", rid)
        if not meta:
            undetermined.append("%s: row %s is missing from the harness" % (theme, rid))
            return None
        r = meta["rect"]
        if r["w"] < 16 or r["h"] < 8:
            undetermined.append(
                "%s: row %s laid out %sx%s, too small to sample an edge band"
                % (theme, rid, r["w"], r["h"]))
            return None
        if (r["x"] < 0 or r["y"] < 0
                or r["x"] + r["w"] > VIEWPORT["width"]
                or r["y"] + r["h"] > VIEWPORT["height"]):
            undetermined.append(
                "%s: row %s lays out at (%s,%s) %sx%s, partly outside the %sx%s "
                "viewport, so an edge pixel cannot be screenshotted. Is the panel "
                "open?" % (theme, rid, r["x"], r["y"], r["w"], r["h"],
                           VIEWPORT["width"], VIEWPORT["height"]))
            return None
        rows[rid] = sample_row(page, meta)
        rows[rid]["label"] = label
        sw = meta.get("swatch")
        rows[rid]["swatch_px"] = (
            sample_pixel(page, sw["x"] + sw["w"] // 2, sw["y"] + sw["h"] // 2)[:3]
            if sw else None)
    return {"theme": theme, "tokens": env["tokens"], "rows": rows}


def report(measured: dict) -> None:
    for theme, m in measured.items():
        print("[%s] --color-border=%s bg=%s accent=%s"
              % (theme, m["tokens"]["border"], m["tokens"]["bg"], m["tokens"]["accent"]))
        for rid, label in ROWS + (CONTROL,):
            row = m["rows"][rid]
            lr = " ".join("%d:%s" % (o, row["left"][o]) for o in BAND_OFFSETS)
            worst = max(C.chan_delta(row["left"][o], row["right"][o])
                        for o in BAND_OFFSETS)
            print("   %-26s border=%s  left[%s]  L/R delta=%d"
                  % (label, row["left"][BORDER_OFFSET], lr, worst))


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("CANNOT DETERMINE: playwright is not importable under %s"
              % sys.executable)
        print("  run with an interpreter that has it, e.g. /opt/homebrew/bin/python3")
        return 2

    failures: list = []
    undetermined: list = []
    measured: dict = {}

    httpd, port = serve(ROOT)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport=VIEWPORT)
            page.goto("http://127.0.0.1:%d%s" % (port, HARNESS))
            try:
                page.wait_for_function("window.__edgesReady === true", timeout=15000)
            except Exception as exc:  # noqa: BLE001
                undetermined.append("harness never became ready: %s" % exc)
            else:
                for theme in THEMES:
                    m = measure_theme(page, theme, undetermined)
                    if m:
                        measured[theme] = m
            browser.close()
    except Exception as exc:  # noqa: BLE001
        undetermined.append("browser could not be driven: %s" % exc)
    finally:
        httpd.shutdown()

    for theme in THEMES:
        if theme in measured:
            m = measured[theme]
            C.check_control(m, CONTROL, failures, undetermined)
            C.check_symmetry(m, ROWS, failures)
            C.check_border_is_theme(m, ROWS, failures, undetermined)
            C.check_active_distinct(m, failures)
            C.check_pinned_is_plain(m, failures)
            C.check_identity_survives(m, failures)
    if len(measured) == len(THEMES):
        C.check_cross_theme(measured[THEMES[0]], measured[THEMES[1]], ROWS, failures)
    elif not undetermined:
        undetermined.append(
            "only %d of %d themes were measured, so the follow-the-theme check "
            "could not run" % (len(measured), len(THEMES)))

    report(measured)

    if undetermined:
        print("\nCANNOT DETERMINE (%d):" % len(undetermined))
        for u in undetermined:
            print("  - %s" % u)
        if failures:
            print("\nalso FAILED (%d):" % len(failures))
            for f in failures:
                print("  - %s" % f)
        return 2
    if failures:
        print("\nFAIL (%d):" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("\nPASS: no sidebar row paints anything on its left edge it does not also "
          "paint on its right, every row carries --color-border on all sides, the "
          "current session is still distinguishable at both its border and its fill, "
          "a pinned row is pixel-identical to a plain one, session identity "
          "survives in the row's swatch, and the rail control was seen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

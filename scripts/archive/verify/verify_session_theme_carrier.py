#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_csp_static_server import serve  # noqa: E402
from lib_pixel_measure import sample_pixel  # noqa: E402
from lib_theme_carrier_checks import (  # noqa: E402
    DIFF_TOL,
    SAME_TOL,
    check_both_directions,
    check_control,
    check_identity_carrier,
    check_launchpad_matches_sidebar,
    chan_delta,
)

ROOT = Path(__file__).resolve().parent.parent
HARNESS = "/tests/manual/session-theme-carrier-harness.html"
VIEWPORT = {"width": 1280, "height": 900}

THEMES = ("claude", "codex", "terminal")

EDGE_OFFSETS = (0, 1, 2)


def settle(page, ids: list) -> None:
    ok = page.evaluate(
        """async (ids) => {
            const snap = () => ids.map((id) => {
                const el = document.getElementById(id);
                if (!el) return 'MISSING:' + id;
                const cs = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return [cs.backgroundColor, cs.backgroundImage, cs.boxShadow,
                        cs.borderLeftColor, cs.borderLeftWidth,
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
            "pixel read here would be the settled one"
        )


def sample_row(page, row: dict) -> dict:
    r = row["rect"]
    mid_y = r["y"] + r["h"] // 2
    row["left"] = {
        off: sample_pixel(page, r["x"] + off, mid_y)[:3] for off in EDGE_OFFSETS
    }
    row["right"] = {
        off: sample_pixel(page, r["x"] + r["w"] - 1 - off, mid_y)[:3]
        for off in EDGE_OFFSETS
    }
    row["fill"] = sample_pixel(page, r["x"] + r["w"] - 6, r["y"] + r["h"] - 4)[:3]
    sw = row.get("swatch")
    if sw:
        s = sw["rect"]
        row["swatch_fill"] = sample_pixel(
            page, s["x"] + s["w"] // 2, s["y"] + s["h"] // 2)[:3]
        row["swatch_edge"] = sample_pixel(page, s["x"], s["y"] + s["h"] // 2)[:3]
    return row


def measure_theme(page, theme: str, session_accent, undetermined: list,
                  density: str = "cozy") -> dict:
    try:
        page.evaluate("(d) => window.__setDensity(d)", density)
        page.evaluate(
            "([id, accent]) => window.__applyTheme(id, accent)",
            [theme, session_accent],
        )
    except Exception as exc:  # noqa: BLE001
        undetermined.append("theme %s would not apply: %s" % (theme, exc))
        return {}

    ids = ["row-plain", "row-themed", "row-active", "row-active-themed",
           "control-accent", "home-plain", "home-themed"]
    try:
        settle(page, ids)
    except RuntimeError as exc:
        undetermined.append("%s: %s" % (theme, exc))
        return {}

    bundle = page.evaluate("window.__carrier()")
    if bundle.get("hidden") or bundle.get("visibilityState") != "visible":
        undetermined.append(
            "%s: tab reported itself hidden (visibilityState=%r). A hidden tab "
            "freezes transitions at frame zero and never fires rAF, so nothing "
            "measured there would mean anything"
            % (theme, bundle.get("visibilityState")))
        return {}
    if bundle.get("innerWidth") != VIEWPORT["width"]:
        undetermined.append(
            "%s: the PAGE reports innerWidth=%r, not the %d asked for. Never "
            "trust a resize tool's own success string - ask the page."
            % (theme, bundle.get("innerWidth"), VIEWPORT["width"]))
        return {}

    if bundle.get("density") != density:
        undetermined.append(
            "%s: the panel reports density=%r, not the %r asked for - never trust "
            "a setter's own success, ask the page"
            % (theme, bundle.get("density"), density))
        return {}
    out = {"theme": theme, "density": density, "tokens": bundle["tokens"],
           "sessionAccent": bundle["sessionAccent"], "rows": {}}
    for row in bundle["rows"]:
        if row is None:
            undetermined.append("%s: a row element is missing from the harness"
                                % theme)
            return {}
        out["rows"][row["id"]] = sample_row(page, row)
    return out


def check_cross_theme(runs: list, failures: list) -> None:
    seen = {}
    for m in runs:
        px = m["rows"]["row-themed"].get("swatch_fill")
        if px is None:
            continue
        seen[(m["theme"], m["sessionAccent"])] = tuple(px)
    values = list(seen.values())
    if len(values) < 2:
        return
    if all(chan_delta(values[0], v) < DIFF_TOL for v in values[1:]):
        failures.append(
            "the swatch pixel is the same colour under every (host theme, "
            "session accent) pair measured (%s) - it is not following the "
            "session's theme at all" % (seen,))


def report(runs: list) -> None:
    for m in runs:
        print("[%s density=%s] accent=%s accent-border=%s border=%s "
              "session-accent=%s"
              % (m["theme"], m["density"], m["tokens"]["accent"],
                 m["tokens"]["accentBorder"], m["tokens"]["border"],
                 m["sessionAccent"]))
        for rid in ("row-plain", "row-themed", "row-active", "row-active-themed",
                    "home-plain", "home-themed"):
            row = m["rows"][rid]
            print("   %-18s edge=%s fill=%s swatch=%s"
                  % (rid, [tuple(row["left"][o]) for o in EDGE_OFFSETS],
                     tuple(row["fill"]),
                     tuple(row["swatch_fill"]) if row.get("swatch_fill") else None))


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
    runs: list = []

    httpd, port = serve(ROOT)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport=VIEWPORT)
            page.goto("http://127.0.0.1:%d%s" % (port, HARNESS))
            try:
                page.wait_for_function("window.__carrierReady === true", timeout=15000)
            except Exception as exc:  # noqa: BLE001
                undetermined.append("harness never became ready: %s" % exc)
            else:
                for theme in THEMES:
                    m = measure_theme(page, theme, None, undetermined)
                    if m:
                        runs.append(m)
                m = measure_theme(page, "claude", "#00CD00", undetermined)
                if m:
                    runs.append(m)
                m = measure_theme(page, "claude", None, undetermined,
                                  density="compact")
                if m:
                    runs.append(m)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        undetermined.append("browser could not be driven: %s" % exc)
    finally:
        httpd.shutdown()

    for m in runs:
        if not check_control(m, undetermined):
            continue
        check_both_directions(m, EDGE_OFFSETS, failures)
        check_identity_carrier(m, failures)
        check_launchpad_matches_sidebar(m, EDGE_OFFSETS, failures)
    check_cross_theme(runs, failures)

    if len(runs) < len(THEMES) + 2 and not undetermined:
        undetermined.append(
            "only %d of %d runs produced measurements, so the follow-the-theme "
            "check could not run" % (len(runs), len(THEMES) + 2))

    report(runs)

    if undetermined:
        print("\nCANNOT DETERMINE (%d):" % len(undetermined))
        for u in undetermined:
            print("  - %s" % u)
    if failures:
        print("\nFAIL (%d):" % len(failures))
        for f in failures:
            print("  - %s" % f)

    if undetermined:
        return 2
    if failures:
        return 1
    print("\nPASS: the border means selection only, selection still reads, and "
          "session identity is carried by the swatch on both surfaces "
          "(SAME_TOL=%d DIFF_TOL=%d)" % (SAME_TOL, DIFF_TOL))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_csp_static_server import serve  # noqa: E402
from lib_pixel_measure import parse_color, sample_pixel  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HARNESS = "/tests/manual/session-stripe-harness.html"

VIEWPORT = {"width": 1280, "height": 900}

THEMES = ("terminal", "codex")

ROWS = (
    ("row-owned", "tmuxFg", "owned, unthemed"),
    ("row-external", "externalFg", "external, unthemed"),
    ("row-owned-themed", "tmuxFg", "owned, data-session-theme"),
    ("row-external-themed", "externalFg", "external, data-session-theme"),
)

SAME_TOL = 6
DIFF_TOL = 24


def chan_delta(a: tuple, b: tuple) -> int:
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


def settle(page, ids: list) -> None:
    ok = page.evaluate(
        """async (ids) => {
            const snap = () => ids.map((id) => {
                const el = document.getElementById(id);
                if (!el) return 'MISSING:' + id;
                const cs = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return [cs.borderLeftColor, cs.borderLeftWidth, cs.borderTopColor,
                        cs.borderTopWidth, cs.backgroundColor,
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
            "computed value read here would be the settled one"
        )


def opaque(css_color: str) -> tuple:
    r, g, b, a = parse_color(css_color)
    if a < 0.999:
        raise RuntimeError(
            "token %r is translucent (alpha %.3f); a screenshot pixel cannot be "
            "compared against it without modelling the backdrop" % (css_color, a)
        )
    return (round(r), round(g), round(b))


def measure_theme(page, theme: str, undetermined: list) -> dict:
    try:
        page.evaluate("(id) => window.__applyTheme(id)", theme)
    except Exception as exc:  # noqa: BLE001
        undetermined.append("theme %s would not apply: %s" % (theme, exc))
        return {}

    settle(page, [rid for rid, _, _ in ROWS] + ["control-stripe"])
    bundle = page.evaluate("window.__stripe()")

    if bundle.get("hidden") or bundle.get("visibilityState") != "visible":
        undetermined.append(
            "tab reported itself hidden (visibilityState=%r); a hidden tab freezes "
            "transitions at frame zero, so nothing measured here would mean "
            "anything" % bundle.get("visibilityState")
        )
        return {}
    if bundle.get("innerWidth") != VIEWPORT["width"]:
        undetermined.append(
            "page reports innerWidth=%r, not the %d asked for - the viewport the "
            "measurements were taken at is not the one this run believes"
            % (bundle.get("innerWidth"), VIEWPORT["width"])
        )
        return {}

    out = {"tokens": bundle["tokens"], "rows": {}, "theme": theme}
    for row in bundle["rows"]:
        if row is None:
            undetermined.append("%s: a row element is missing from the harness" % theme)
            return {}
        rect = row["rect"]
        x = round(rect["x"])
        y = round(rect["y"] + rect["h"] / 2.0)
        row["edge_pixel"] = sample_pixel(page, x, y)[:3]
        row["sample_point"] = (x, y)
        row["fill_pixel"] = sample_pixel(
            page, round(rect["x"] + rect["w"] - 12), round(rect["y"] + rect["h"] - 4)
        )[:3]
        out["rows"][row["id"]] = row

    ctrl = bundle["control"]
    if ctrl is None:
        undetermined.append("%s: the positive-control stripe is missing" % theme)
        return {}
    out["control"] = sample_pixel(
        page, round(ctrl["rect"]["x"]), round(ctrl["rect"]["y"] + ctrl["rect"]["h"] / 2)
    )[:3]
    return out


def check_theme(m: dict, failures: list, undetermined: list) -> None:
    theme = m["theme"]
    try:
        border = opaque(m["tokens"]["border"])
    except (RuntimeError, ValueError) as exc:
        undetermined.append("%s: --color-border unusable: %s" % (theme, exc))
        return

    try:
        tmux = opaque(m["tokens"]["tmuxFg"])
    except (RuntimeError, ValueError) as exc:
        undetermined.append("%s: --color-badge-tmux-fg unusable: %s" % (theme, exc))
        return
    d = chan_delta(m["control"], tmux)
    if d > SAME_TOL:
        undetermined.append(
            "%s: POSITIVE CONTROL FAILED - the control stripe is painted "
            "--color-badge-tmux-fg %s and sampled as %s (delta %d). The sampler "
            "cannot see this colour, so 'the rows are not this colour' is not a "
            "measurement." % (theme, tmux, tuple(m["control"]), d)
        )
        return

    for rid, token_key, label in ROWS:
        row = m["rows"][rid]
        try:
            type_color = opaque(m["tokens"][token_key])
        except (RuntimeError, ValueError) as exc:
            undetermined.append("%s/%s: %s token unusable: %s"
                                % (theme, rid, token_key, exc))
            continue

        w = row["widths"]
        if len(set(w.values())) != 1:
            failures.append(
                "%s/%s (%s): the four border widths disagree (%s). The left edge is "
                "not coherent with its three neighbours."
                % (theme, rid, label, w))
        if w["left"] in ("0px", "0"):
            failures.append(
                "%s/%s (%s): border-left-width is 0 - the row has no left border at "
                "all, which is a ragged edge, not a themed one"
                % (theme, rid, label))
        c = row["colors"]
        if len(set(c.values())) != 1:
            failures.append(
                "%s/%s (%s): the four border colours disagree (%s)"
                % (theme, rid, label, c))

        px = tuple(row["edge_pixel"])
        d_type = chan_delta(px, type_color)
        if d_type < DIFF_TOL:
            failures.append(
                "%s/%s (%s): the left-edge PIXEL at %s is %s, which is the "
                "session-type colour %s (delta %d). This is the reported bug: the "
                "row's left edge still encodes session type."
                % (theme, rid, label, row["sample_point"], px, type_color, d_type))
        d_border = chan_delta(px, border)
        if d_border > SAME_TOL:
            failures.append(
                "%s/%s (%s): the left-edge PIXEL at %s is %s, but the theme's "
                "--color-border is %s (delta %d). The edge is not coming from the "
                "theme."
                % (theme, rid, label, row["sample_point"], px, border, d_border))


def check_cross_theme(a: dict, b: dict, failures: list) -> None:
    for rid, _, label in ROWS:
        edge_a = tuple(a["rows"][rid]["edge_pixel"])
        edge_b = tuple(b["rows"][rid]["edge_pixel"])
        if chan_delta(edge_a, edge_b) < DIFF_TOL:
            failures.append(
                "%s (%s): the left-edge pixel is %s under %s and %s under %s - it "
                "did not follow the theme change, so matching one theme's token was "
                "a coincidence" % (rid, label, edge_a, a["theme"], edge_b, b["theme"]))
        fill_a = tuple(a["rows"][rid]["fill_pixel"])
        fill_b = tuple(b["rows"][rid]["fill_pixel"])
        if chan_delta(fill_a, fill_b) < DIFF_TOL:
            failures.append(
                "%s (%s): the row BACKGROUND pixel is %s under %s and %s under %s - "
                "the fill is not theme-derived either"
                % (rid, label, fill_a, a["theme"], fill_b, b["theme"]))


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
                page.wait_for_function("window.__stripeReady === true", timeout=15000)
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
            check_theme(measured[theme], failures, undetermined)
    if len(measured) == len(THEMES):
        check_cross_theme(measured[THEMES[0]], measured[THEMES[1]], failures)
    elif not undetermined:
        undetermined.append(
            "only %d of %d themes were measured, so the follow-the-theme check "
            "could not run" % (len(measured), len(THEMES)))

    for theme, m in measured.items():
        print("[%s] --color-border=%s  tmux-fg=%s  external-fg=%s"
              % (theme, m["tokens"]["border"], m["tokens"]["tmuxFg"],
                 m["tokens"]["externalFg"]))
        for rid, _, label in ROWS:
            row = m["rows"][rid]
            print("   %-20s widths=%s edge_px=%s fill_px=%s"
                  % (label, [row["widths"][k] for k in ("top", "right", "bottom", "left")],
                     tuple(row["edge_pixel"]), tuple(row["fill_pixel"])))

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
    print("\nPASS: every row's left edge is --color-border in both themes, all four "
          "sides agree, no session-type colour anywhere on the edge, and both the "
          "edge and the fill changed when the theme did.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

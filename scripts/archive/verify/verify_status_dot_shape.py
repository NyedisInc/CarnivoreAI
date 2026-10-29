#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_csp_static_server import serve  # noqa: E402
from lib_pixel_measure import parse_color, sample_pixel  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HARNESS = "/tests/manual/status-dot-shape-harness.html"

VIEWPORT = {"width": 1280, "height": 900}

THEMES = ("claude", "terminal", "codex")

HOLLOW_STATE = "unknown"
FILLED_STATES = ("dead", "question", "working_subagent", "working",
                 "finished_unread", "idle")

SAME_TOL = 6
DIFF_TOL = 24


def chan_delta(a: tuple, b: tuple) -> int:
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


def sample_points(rect: dict) -> tuple:
    x, y = round(rect["x"]), round(rect["y"])
    return ((x + 4, y + 4), (x + 1, y + 4))


def settle(page, states: list) -> None:
    ok = page.evaluate(
        """async (states) => {
            const snap = () => states.map((s) => {
                const cell = document.getElementById('cell-' + s);
                const el = cell ? cell.querySelector('.status-dot') : null;
                if (!el) return 'MISSING:' + s;
                const cs = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return [cs.backgroundColor, cs.boxShadow, cs.borderRadius,
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
        states,
    )
    if not ok:
        raise RuntimeError(
            "dot paint never stopped changing across 90 animation frames, so no "
            "value read here would be the settled one"
        )


def opaque(css_color: str) -> tuple:
    r, g, b, a = parse_color(css_color)
    if a < 0.999:
        raise RuntimeError(
            "token %r is translucent (alpha %.3f); a screenshot pixel cannot be "
            "compared against it without modelling the backdrop" % (css_color, a))
    return (round(r), round(g), round(b))


def measure_theme(page, theme: str, undetermined: list) -> dict:
    try:
        page.evaluate("(id) => window.__applyTheme(id)", theme)
    except Exception as exc:  # noqa: BLE001
        undetermined.append("theme %s would not apply: %s" % (theme, exc))
        return {}

    settle(page, list(FILLED_STATES) + [HOLLOW_STATE])
    bundle = page.evaluate("window.__dots()")

    if bundle.get("hidden") or bundle.get("visibilityState") != "visible":
        undetermined.append(
            "%s: tab reported itself hidden (visibilityState=%r); a hidden tab "
            "freezes transitions at frame zero and never fires rAF, so nothing "
            "measured there would mean anything"
            % (theme, bundle.get("visibilityState")))
        return {}
    if bundle.get("innerWidth") != VIEWPORT["width"]:
        undetermined.append(
            "%s: page reports innerWidth=%r, not the %d asked for - the viewport "
            "the measurements were taken at is not the one this run believes"
            % (theme, bundle.get("innerWidth"), VIEWPORT["width"]))
        return {}
    if bundle.get("devicePixelRatio") != 1:
        undetermined.append(
            "%s: devicePixelRatio is %r, not 1. The sample points are CSS-pixel "
            "offsets worked out against a 9px box; at another ratio they no "
            "longer land where this file says they land"
            % (theme, bundle.get("devicePixelRatio")))
        return {}

    out = {"theme": theme, "tokens": bundle["tokens"], "dots": {}}
    for dot in bundle["dots"]:
        if dot is None:
            undetermined.append("%s: a status dot is missing from the harness" % theme)
            return {}
        if round(dot["rect"]["w"]) != 9 or round(dot["rect"]["h"]) != 9:
            undetermined.append(
                "%s/%s: the dot measured %sx%s, not the 9x9 the sample points "
                "were derived from"
                % (theme, dot["state"], dot["rect"]["w"], dot["rect"]["h"]))
            return {}
        centre, rim = sample_points(dot["rect"])
        dot["centre_px"] = sample_pixel(page, centre[0], centre[1],
                                        freeze_animations=True)[:3]
        dot["rim_px"] = sample_pixel(page, rim[0], rim[1],
                                     freeze_animations=True)[:3]
        dot["points"] = {"centre": centre, "rim": rim}
        out["dots"][dot["state"]] = dot

    for key, name in (("controlFilled", "control-filled"),
                      ("controlHollow", "control-hollow")):
        box = bundle.get(key)
        if box is None:
            undetermined.append("%s: the %s positive control is missing" % (theme, name))
            return {}
        centre, rim = sample_points(box["rect"])
        out[key] = {
            "centre_px": sample_pixel(page, centre[0], centre[1],
                                      freeze_animations=True)[:3],
            "rim_px": sample_pixel(page, rim[0], rim[1], freeze_animations=True)[:3],
            "points": {"centre": centre, "rim": rim},
        }
    return out


def check_controls(m: dict, undetermined: list) -> bool:
    theme = m["theme"]
    f, h = m["controlFilled"], m["controlHollow"]
    df = chan_delta(f["centre_px"], f["rim_px"])
    dh = chan_delta(h["centre_px"], h["rim_px"])
    ok = True
    if df > SAME_TOL:
        undetermined.append(
            "%s: POSITIVE CONTROL FAILED - #control-filled is a deliberately SOLID "
            "box and its centre %s does not match its rim %s (delta %d). The "
            "sampler cannot recognise a filled shape, so 'these dots are filled' "
            "would not be a measurement."
            % (theme, tuple(f["centre_px"]), tuple(f["rim_px"]), df))
        ok = False
    if dh < DIFF_TOL:
        undetermined.append(
            "%s: POSITIVE CONTROL FAILED - #control-hollow is a deliberately HOLLOW "
            "box and its centre %s matches its rim %s (delta %d). The sampler "
            "cannot recognise a hollow shape, so 'unknown is hollow' would not be "
            "a measurement."
            % (theme, tuple(h["centre_px"]), tuple(h["rim_px"]), dh))
        ok = False
    return ok


def check_theme(m: dict, failures: list, undetermined: list) -> None:
    theme = m["theme"]
    if not check_controls(m, undetermined):
        return
    try:
        bg = opaque(m["tokens"]["bg"])
    except (RuntimeError, ValueError) as exc:
        undetermined.append("%s: --color-bg unusable: %s" % (theme, exc))
        return

    for state in FILLED_STATES:
        dot = m["dots"][state]
        d = chan_delta(dot["centre_px"], dot["rim_px"])
        if d > SAME_TOL:
            failures.append(
                "%s/%s: the dot is NOT solid - centre %s at %s versus rim %s at %s "
                "(delta %d). A definite status must read as a filled dot; hollow "
                "is reserved for the state the server could not determine."
                % (theme, state, tuple(dot["centre_px"]), dot["points"]["centre"],
                   tuple(dot["rim_px"]), dot["points"]["rim"], d))

    unk = m["dots"][HOLLOW_STATE]
    d = chan_delta(unk["centre_px"], unk["rim_px"])
    if d < DIFF_TOL:
        failures.append(
            "%s/unknown: the dot renders SOLID - centre %s at %s and rim %s at %s "
            "are the same colour (delta %d). This is the reported defect: a "
            "could-not-determine is drawn as a definite answer."
            % (theme, tuple(unk["centre_px"]), unk["points"]["centre"],
               tuple(unk["rim_px"]), unk["points"]["rim"], d))
    d_bg = chan_delta(unk["centre_px"], bg)
    if d_bg > SAME_TOL:
        failures.append(
            "%s/unknown: the centre pixel %s is not the page backdrop %s "
            "(delta %d), so the ring is not actually see-through - something is "
            "still painting the middle."
            % (theme, tuple(unk["centre_px"]), bg, d_bg))
    d_rim = chan_delta(unk["rim_px"], bg)
    if d_rim < DIFF_TOL:
        failures.append(
            "%s/unknown: the rim pixel %s is the backdrop %s (delta %d) - the ring "
            "has no ink, which is an invisible dot, not a legible one."
            % (theme, tuple(unk["rim_px"]), bg, d_rim))

    idle = m["dots"]["idle"]
    d_pair = chan_delta(idle["centre_px"], unk["centre_px"])
    if d_pair < DIFF_TOL:
        failures.append(
            "%s: idle and unknown still look the same - idle's centre is %s and "
            "unknown's centre is %s (delta %d). Separating them is the entire "
            "purpose of this change."
            % (theme, tuple(idle["centre_px"]), tuple(unk["centre_px"]), d_pair))


def check_radius_zero(measured: dict, failures: list, undetermined: list) -> None:
    zeroed = [t for t, m in measured.items()
              if m["tokens"]["radiusFull"].strip() in ("0", "0px", "0%")]
    if not zeroed:
        undetermined.append(
            "no measured theme zeroes --radius-full, so the radius-zeroing themes "
            "(terminal, gameboy, legacy_apple) were never exercised and this run "
            "cannot say the ring survives them")
        return
    for t in zeroed:
        unk = measured[t]["dots"][HOLLOW_STATE]
        if chan_delta(unk["centre_px"], unk["rim_px"]) < DIFF_TOL:
            failures.append(
                "%s zeroes --radius-full and unknown went solid there (centre %s, "
                "rim %s). The ring collapsed with the radius token."
                % (t, tuple(unk["centre_px"]), tuple(unk["rim_px"])))


def check_cross_theme(measured: dict, failures: list) -> None:
    rims = {t: tuple(m["dots"][HOLLOW_STATE]["rim_px"]) for t, m in measured.items()}
    pairs = [(a, b) for a in rims for b in rims if a < b]
    if not any(chan_delta(rims[a], rims[b]) >= DIFF_TOL for a, b in pairs):
        failures.append(
            "unknown's rim pixel is the same across every theme measured (%s) - it "
            "is not following the palette, so it is painted from something other "
            "than a theme token" % rims)


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
                page.wait_for_function("window.__dotsReady === true", timeout=15000)
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
        check_radius_zero(measured, failures, undetermined)
        check_cross_theme(measured, failures)
    elif not undetermined:
        undetermined.append(
            "only %d of %d themes were measured, so the cross-theme and "
            "radius-zero checks could not run" % (len(measured), len(THEMES)))

    for theme, m in measured.items():
        print("[%s] bg=%s fg-faint=%s fg-subtle=%s radius-full=%r"
              % (theme, m["tokens"]["bg"], m["tokens"]["fgFaint"],
                 m["tokens"]["fgSubtle"], m["tokens"]["radiusFull"]))
        for state in list(FILLED_STATES) + [HOLLOW_STATE]:
            dot = m["dots"][state]
            print("   %-17s centre=%-16s rim=%-16s delta=%3d  %s"
                  % (state, tuple(dot["centre_px"]), tuple(dot["rim_px"]),
                     chan_delta(dot["centre_px"], dot["rim_px"]),
                     "HOLLOW" if chan_delta(dot["centre_px"], dot["rim_px"])
                     >= DIFF_TOL else "filled"))

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
    print("\nPASS: unknown renders hollow and every definite status renders filled, "
          "in all %d themes, including one that zeroes every radius token, with the "
          "rim following the palette and both positive controls behaving."
          % len(measured))
    return 0


if __name__ == "__main__":
    sys.exit(main())

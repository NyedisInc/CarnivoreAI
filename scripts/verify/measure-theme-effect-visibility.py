"""Measure whether each theme's background effect is VISIBLE, not merely running.

THE INCIDENT THIS INSTRUMENT COMES FROM. All 23 themes shipped animated canvas
backgrounds. Every automated check said they worked: canvas mounted, rAF loop
live, status "running", clean teardown on theme switch. Measured here, the
maximum composited RGB delta between the page with the effect running and the
same page with the canvas hidden was 0/255 for all 23 - including matrix, whose
canvas held pixels spanning the full 0-255 green range. The effects were
painting perfectly underneath an opaque `body` background.

"Running" is not "visible". Only a pixel diff distinguishes them, so this
script takes one.

WHAT IT MEASURES, per theme:
  1. canvas self-paint - getImageData on the canvas itself, so an effect that
     draws nothing is distinguished from one that draws and is covered
  2. occlusion - the composited paint stack at the viewport centre, with the
     computed background-color and z-index of every element above the canvas
  3. perceived delta - screenshot with the effect running MINUS screenshot with
     the canvas display:none, reported as max and mean absolute RGB in 0-255

  Plus a NOISE FLOOR control: two screenshots taken back to back with the canvas
  hidden both times. Without it a nonzero delta could be any other animation on
  the page. It reads 0 for every theme, which is what makes the rest credible.

THREE OUTCOMES. A theme that cannot be driven is reported as an error row, not
as a pass and not as a zero. A zero delta with a painting canvas is a FAIL
(occluded); a zero delta with a blank canvas is a different fail (draws
nothing); a theme whose page never loaded is CANNOT EVALUATE.

Requires the playwright Python package and its chromium build. The repo does
not depend on either at runtime - this is an instrument, run by hand, and the
numbers it produces are committed to
tests/fixtures/theme-effect-visibility-baseline.json so the node suite can
guard them without a browser.

Usage:
    python3 scripts/verify/measure-theme-effect-visibility.py [theme,theme,...]
        [--screen launchpad-screen] [--tag run1] [--port 5057]

    With no theme list, every bundled theme with an effects module is measured.
    Screenshots are written to scripts/verify/.theme-effect-shots/ (gitignored)
    and JSON results to stdout, one object per line.
"""
import argparse
import json
import os
import sys
from typing import Any, Callable

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, HERE)
from theme_harness import check_port, image_diff, run_theme_sweep  # noqa: E402
THEMES_DIR = os.path.join(REPO_ROOT, "client", "css", "themes")
SHOTS = os.path.join(HERE, ".theme-effect-shots")

CANVAS_SELECTOR = "body > canvas[aria-hidden='true']"

PROBE_JS = """
() => {
  const c = document.querySelector("%s");
  const out = { canvas: !!c, status: document.documentElement.dataset.themeEffects || null };
  if (c) {
    out.cw = c.width; out.ch = c.height;
    const cs = getComputedStyle(c);
    out.canvasZ = cs.zIndex; out.canvasPos = cs.position;
    try {
      const ctx = c.getContext('2d');
      const d = ctx.getImageData(0, 0, c.width, c.height).data;
      let mn = [255,255,255,255], mx = [0,0,0,0], n = 0;
      const step = 4 * 37;   // prime stride, roughly 1 pixel in 37
      for (let i = 0; i < d.length; i += step) {
        n++;
        for (let k = 0; k < 4; k++) {
          if (d[i+k] < mn[k]) mn[k] = d[i+k];
          if (d[i+k] > mx[k]) mx[k] = d[i+k];
        }
      }
      out.sampled = n;
      // Spread proves the canvas holds a real image rather than a flat fill.
      out.canvasSpread = [mx[0]-mn[0], mx[1]-mn[1], mx[2]-mn[2], mx[3]-mn[3]];
    } catch (e) { out.getImageDataError = String(e); }
  }
  const cx = Math.round(innerWidth/2), cy = Math.round(innerHeight/2);
  out.stack = document.elementsFromPoint(cx, cy).map(el => {
    const s = getComputedStyle(el);
    return {
      tag: el.tagName.toLowerCase(), id: el.id || null,
      bg: s.backgroundColor, z: s.zIndex, pos: s.position,
      opacity: s.opacity, transform: s.transform, filter: s.filter,
      isolation: s.isolation, willChange: s.willChange, contain: s.contain
    };
  });
  // elementsFromPoint omits html/body once something covers them, and those
  // two are exactly the elements that caused the bug, so read them directly.
  out.rootChain = ['html','body'].map(sel => {
    const el = document.querySelector(sel), s = getComputedStyle(el);
    return { tag: sel, bg: s.backgroundColor, z: s.zIndex, pos: s.position,
             transform: s.transform, filter: s.filter, opacity: s.opacity,
             isolation: s.isolation, willChange: s.willChange };
  });
  return out;
}
""" % CANVAS_SELECTOR

SET_CANVAS_DISPLAY = """
(v) => { const c = document.querySelector("%s"); if (c) c.style.display = v; }
""" % CANVAS_SELECTOR


def effect_themes() -> list[str]:
    out = []
    for name in sorted(os.listdir(THEMES_DIR)):
        path = os.path.join(THEMES_DIR, name, "theme.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            if json.load(fh).get("effects"):
                out.append(name)
    return out


def diff(png_a: bytes, png_b: bytes) -> dict:
    return image_diff(png_a, png_b, with_changed_pct=True)


def measure(page: Any, base: str, theme: str, screen: str) -> tuple[dict, bytes, bytes]:
    page.goto(base, wait_until="load", timeout=20000)
    assert page.evaluate("window.innerWidth") == 1280, "viewport did not take"
    page.wait_for_function("() => !!(window.Themes && window.Themes.init)", timeout=15000)
    page.evaluate("async () => { await window.Themes.init(); }")
    page.evaluate("(t) => window.Themes.applyGlobal(t)", theme)
    page.wait_for_timeout(400)
    page.evaluate(
        """(s) => {
            document.querySelectorAll('.screen').forEach(e => e.classList.remove('active'));
            const t = document.getElementById(s);
            if (t) t.classList.add('active');
        }""",
        screen,
    )
    page.wait_for_timeout(2400)

    row = {"theme": theme, "probe": page.evaluate(PROBE_JS)}

    page.evaluate(SET_CANVAS_DISPLAY, "none")
    page.wait_for_timeout(500)
    plate_a = page.screenshot()
    page.wait_for_timeout(700)
    plate_b = page.screenshot()
    row["noiseFloor"] = diff(plate_a, plate_b)

    page.evaluate(SET_CANVAS_DISPLAY, "")
    page.wait_for_timeout(900)
    live = page.screenshot()
    row["delta"] = diff(live, plate_b)
    return row, live, plate_b


def verdict(row: dict) -> str:
    if "error" in row:
        return "CANNOT EVALUATE: " + row["error"]
    probe = row.get("probe", {})
    if not probe.get("canvas"):
        return "CANNOT EVALUATE: no effects canvas was mounted"
    dmax = row["delta"]["max"]
    if row["noiseFloor"]["max"] > 0:
        return f"CANNOT EVALUATE: noise floor is {row['noiseFloor']['max']}, not 0"
    if dmax == 0:
        spread = max(probe.get("canvasSpread") or [0])
        if spread > 0:
            return "FAIL: canvas is painting but composites to 0 - it is occluded"
        return "FAIL: canvas composites to 0 and is also blank - it draws nothing"
    if dmax < 3:
        return f"FAIL: max delta {dmax}/255 is below the perception threshold"
    if dmax < 8:
        return f"WEAK: max delta {dmax}/255 is subliminal on a normal display"
    return f"PASS: max delta {dmax}/255"


def measure_and_save(args: argparse.Namespace) -> Callable[[Any, str, str], dict]:
    def run(page: Any, base: str, theme: str) -> dict:
        row, live, plate = measure(page, base, theme, args.screen)
        for suffix, data in (("on", live), ("off", plate)):
            with open(os.path.join(SHOTS, f"{args.tag}_{theme}_{suffix}.png"), "wb") as fh:
                fh.write(data)
        return row
    return run


def add_verdict(row: dict) -> dict:
    row["verdict"] = verdict(row)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("themes", nargs="?", default="", help="comma-separated theme ids")
    ap.add_argument("--screen", default="launchpad-screen")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--port", type=int, default=5057)
    args = ap.parse_args()

    if not check_port(args.port):
        return 2
    themes = [t for t in args.themes.split(",") if t] or effect_themes()
    os.makedirs(SHOTS, exist_ok=True)
    rows = run_theme_sweep(themes, args.port, measure_and_save(args), add_verdict)
    if rows is None:
        return 2

    print(f"\nscreenshots: {SHOTS}", file=sys.stderr)
    print("LOOK AT THEM. A delta is a number; only your eyes confirm it reads "
          "as the effect the theme intended.", file=sys.stderr)
    bad = [r for r in rows if not r["verdict"].startswith("PASS")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

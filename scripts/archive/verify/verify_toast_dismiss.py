#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_csp_static_server import (  # noqa: E402
    collector_init_script,
    serve,
    violations,
)

ROOT = Path(__file__).resolve().parent.parent
HARNESS = "/tests/manual/toast-dismiss-harness.html"

THEMES = ("claude", "terminal")
VIEWPORTS = (("desktop", 1280, 900, 3), ("phone", 390, 844, 2))

FAILURES: list[str] = []
UNDETERMINED: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)


def undet(msg: str) -> None:
    UNDETERMINED.append(msg)


def measure(page, tag: str, width: int) -> dict | None:
    if not page.evaluate("() => window.__settle()"):
        undet(f"{tag}: paint never stopped changing across 180 frames, so no "
              f"read here would be the settled one")
        return None
    b = page.evaluate("() => window.__measure()")
    if b.get("hidden") or b.get("visibilityState") != "visible":
        undet(f"{tag}: tab reported itself hidden "
              f"(visibilityState={b.get('visibilityState')!r}). A hidden tab "
              f"freezes transitions at frame zero and never fires rAF")
        return None
    if b.get("innerWidth") != width:
        undet(f"{tag}: the PAGE reports innerWidth={b.get('innerWidth')!r}, not "
              f"the {width} asked for. Never trust a resize tool's own success "
              f"string - ask the page")
        return None
    return b


def painted(cards: list) -> list:
    return [c for c in cards if c["box"] and c["box"]["painted"]]


def run_case(page, tag: str, width: int, cap: int) -> None:
    page.evaluate("() => window.__control()")
    b = measure(page, f"{tag}/control", width)
    if b is None:
        return
    ctrl = painted(b["cards"])
    if len(ctrl) != 1:
        undet(f"{tag}: positive control painted {len(ctrl)} cards, not 1. The "
              f"sampler is blind, so every disappearance verdict in this run "
              f"would pass while measuring nothing")
        return
    if ctrl[0]["box"]["w"] < 100 or ctrl[0]["box"]["h"] < 20:
        undet(f"{tag}: positive control card measured "
              f"{ctrl[0]['box']['w']}x{ctrl[0]['box']['h']}, too small to be a "
              f"rendered toast. Blind sampler")
        return

    page.evaluate("""() => {
        window.__reset();
        window.__add('Stop', 'Your turn', 'A');
        window.__add('PermissionRequest', 'Allow Bash?', 'B', 'rm -rf /tmp/x');
    }""")
    b = measure(page, f"{tag}/negctl", width)
    if b is None:
        return
    if len(painted(b["cards"])) != 2:
        undet(f"{tag}: negative control painted "
              f"{len(painted(b['cards']))} cards, not 2. Nothing was dismissed "
              f"here, so a stack that is already empty means the disappearance "
              f"claims below measure nothing")
        return

    page.evaluate("() => window.__typeInto('B')")
    b = measure(page, f"{tag}/type-into-B", width)
    if b is None:
        return
    left = painted(b["cards"])
    if len(left) != 1:
        fail(f"{tag}: after input to session B, {len(left)} cards paint, not 1 "
             f"- A's toast must survive B's keystrokes")
    elif left[0]["title"] != "Your turn":
        fail(f"{tag}: input to B dismissed the wrong card; what is left reads "
             f"{left[0]['title']!r}")

    page.evaluate("() => window.__typeInto('A')")
    b = measure(page, f"{tag}/type-into-A", width)
    if b is None:
        return
    if painted(b["cards"]):
        fail(f"{tag}: after input to session A, "
             f"{len(painted(b['cards']))} cards still paint - the toast the "
             f"user just answered is still on screen")

    page.evaluate("() => window.__add('Notification', 'later', 'A', 'body')")
    b = measure(page, f"{tag}/after-input-not-muted", width)
    if b is None:
        return
    if len(painted(b["cards"])) != 1:
        fail(f"{tag}: a toast raised AFTER an input-dismissal painted "
             f"{len(painted(b['cards']))} cards, not 1 - the dismissal muted "
             f"the feature instead of clearing the stack")

    page.evaluate("""() => {
        window.__reset();
        window.__add('Stop', 'Your turn', 'A');
        window.__add('Notification', 'other', 'B', 'b');
        window.__add('PermissionRequest', 'Allow?', 'C', 'cmd');
    }""")
    b = measure(page, f"{tag}/dismiss-all-setup", width)
    if b is None:
        return
    want_visible = min(3, cap)
    if len(painted(b["cards"])) != want_visible:
        undet(f"{tag}: Dismiss all negative control painted "
              f"{len(painted(b['cards']))} cards, not the {want_visible} the "
              f"cap allows")
        return
    da = b["dismissAll"]
    if not da:
        fail(f"{tag}: three toasts on screen and no Dismiss all control exists")
    elif not da["box"]["painted"]:
        fail(f"{tag}: the Dismiss all control is in the DOM but paints no box "
             f"({da['box']}). A control nobody can see is not a control")
    elif da["box"]["w"] < 80 or da["box"]["h"] < 16:
        fail(f"{tag}: Dismiss all control box is {da['box']['w']}x"
             f"{da['box']['h']}, too small to read or hit")
    elif da["text"] != "Dismiss all (3)":
        fail(f"{tag}: the control reads {da['text']!r}, not 'Dismiss all (3)'")
    elif da["blocking"] != "1" or "permission" not in (da["ariaLabel"] or ""):
        fail(f"{tag}: the stack holds a blocking prompt and the control does "
             f"not disclose it (blocking={da['blocking']!r}, "
             f"aria-label={da['ariaLabel']!r})")

    if not page.evaluate("() => window.__clickDismissAll()"):
        undet(f"{tag}: could not click the Dismiss all control")
        return
    b = measure(page, f"{tag}/dismiss-all", width)
    if b is None:
        return
    if painted(b["cards"]):
        fail(f"{tag}: after Dismiss all, {len(painted(b['cards']))} cards still "
             f"paint: {[c['title'] for c in painted(b['cards'])]}")
    if b["dismissAll"] and b["dismissAll"]["box"]["painted"]:
        fail(f"{tag}: the Dismiss all control still paints over an empty stack")

    page.evaluate("() => window.__add('Stop', 'Your turn', 'A', 'fresh')")
    b = measure(page, f"{tag}/after-dismiss-all-not-muted", width)
    if b is None:
        return
    if len(painted(b["cards"])) != 1:
        fail(f"{tag}: a toast raised AFTER Dismiss all painted "
             f"{len(painted(b['cards']))} cards, not 1 - the control muted the "
             f"feature instead of clearing the stack")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        print(f"CANNOT DETERMINE: playwright not importable ({exc}). Run with "
              f"an interpreter that has it.")
        return 2

    httpd, port = serve(ROOT)
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as exc:  # noqa: BLE001
                print(f"CANNOT DETERMINE: chromium would not launch ({exc})")
                return 2
            for vp_name, width, height, cap in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.add_init_script(collector_init_script())
                page.goto(f"http://127.0.0.1:{port}{HARNESS}")
                try:
                    page.wait_for_function("() => window.__ready === true",
                                           timeout=15000)
                except Exception as exc:  # noqa: BLE001
                    undet(f"{vp_name}: harness never became ready ({exc})")
                    page.close()
                    continue
                for theme in THEMES:
                    tag = f"{theme}/{vp_name}"
                    try:
                        page.evaluate("(t) => window.__setTheme(t)", theme)
                    except Exception as exc:  # noqa: BLE001
                        undet(f"{tag}: theme would not apply ({exc})")
                        continue
                    run_case(page, tag, width, cap)
                for v in violations(page):
                    undet(f"{vp_name}: CSP violation on the harness ({v}). The "
                          f"page did not run as production would")
                page.close()
            browser.close()
    finally:
        httpd.shutdown()

    if UNDETERMINED:
        print("CANNOT DETERMINE:")
        for m in UNDETERMINED:
            print(f"  - {m}")
        for m in FAILURES:
            print(f"  (also measured and wrong: {m})")
        return 2
    if FAILURES:
        print("FAIL:")
        for m in FAILURES:
            print(f"  - {m}")
        return 1
    print(f"PASS: per-session input dismissal, cross-session non-dismissal, "
          f"the Dismiss all control and both not-muted checks "
          f"measured as painted boxes across {len(THEMES)} themes x "
          f"{len(VIEWPORTS)} viewports")
    return 0


if __name__ == "__main__":
    sys.exit(main())

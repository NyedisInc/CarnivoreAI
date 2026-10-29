#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib_csp_static_server import (  # noqa: E402
    collector_init_script,
    serve,
    violations,
)

HARNESS = "/tests/manual/session-name-surfaces-harness.html"
VIEWPORTS = (("desktop", 1280, 900), ("phone", 390, 844))
BRAND = "Cloude Code"

HAIRY_LABEL = 'client: acme v2.1 "prod" $rate'

FAILURES: list[str] = []
UNDETERMINED: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)


def undet(msg: str) -> None:
    UNDETERMINED.append(msg)


def measure(page, tag: str, width: int):
    b = page.evaluate("() => window.__measure()")
    vp = b.get("viewport") or {}
    if vp.get("hidden") or vp.get("visibilityState") != "visible":
        undet(
            f"{tag}: the tab reported itself hidden "
            f"(visibilityState={vp.get('visibilityState')!r}). A hidden tab "
            f"freezes transitions at frame zero and never fires rAF, so "
            f"nothing measured there would mean anything"
        )
        return None
    if vp.get("innerWidth") != width:
        undet(
            f"{tag}: the PAGE reports innerWidth={vp.get('innerWidth')!r}, not "
            f"the {width} asked for. Never trust a resize tool's own success "
            f"string - ask the page"
        )
        return None
    return b


def check_tab_title(page, tag: str, width: int) -> None:
    page.evaluate("() => window.__reset()")
    title = page.evaluate(
        "(l) => window.__title({label: l, name: 'cloude_Media'})", HAIRY_LABEL
    )
    if title != f"{HAIRY_LABEL} - {BRAND}":
        fail(
            f"{tag}: a labelled session's tab title reads {title!r}. The label "
            f"is what the user named this session and it is what the tab must "
            f"say, verbatim, punctuation included"
        )

    title = page.evaluate(
        "() => window.__title({label: null, name: 'cloude_Media'})"
    )
    if title != f"Media - {BRAND}":
        fail(
            f"{tag}: an UNLABELLED session's tab title reads {title!r}, not "
            f"'Media - {BRAND}'. Every session that existed before labels did "
            f"is in this case; it must look exactly as it always did"
        )

    title = page.evaluate("() => window.__title({label: '   ', name: 'cloude_Media'})")
    if title != f"Media - {BRAND}":
        fail(
            f"{tag}: an empty-string label produced the tab title {title!r}. "
            f"An empty label is NO label, never a blank name"
        )

    title = page.evaluate("() => window.__title({label: null, name: null})")
    if "null" in title or "undefined" in title or "[object" in title:
        fail(
            f"{tag}: an unnameable session produced the tab title {title!r}. "
            f"A stringified null in a browser tab is worse than the brand"
        )
    if title != BRAND:
        fail(
            f"{tag}: a session that cannot be named produced {title!r}; the tab "
            f"must fall back to the bare brand"
        )

    title = page.evaluate("() => window.__title({name: 'someones-shell'})")
    if title != f"someones-shell - {BRAND}":
        fail(f"{tag}: an external session's tab title reads {title!r}")

    title = page.evaluate("() => window.__title(null)")
    if title != BRAND:
        fail(f"{tag}: leaving a session left the tab titled {title!r}")


def check_toast(page, tag: str, width: int) -> None:
    cases = (
        (
            {"session_label": HAIRY_LABEL, "session_name": "cloude_Media"},
            HAIRY_LABEL,
            "a labelled session",
        ),
        (
            {"session_label": None, "session_name": "cloude_Media"},
            "Media",
            "an unlabelled session",
        ),
        (
            {"session_label": "", "session_name": "cloude_Media"},
            "Media",
            "an empty-string label",
        ),
        (
            {"session_label": None, "session_name": "someones-shell"},
            "someones-shell",
            "an external session",
        ),
    )
    for identity, expected, what in cases:
        page.evaluate("() => window.__reset()")
        page.evaluate("(i) => window.__toast(i)", identity)
        b = measure(page, f"{tag}/toast", width)
        if b is None:
            return
        if not b["sessionPresent"]:
            fail(
                f"{tag}: a toast for {what} renders NO session line at all. A "
                f"toast can arrive for a session that is not on screen; if it "
                f"does not say which one, it is unactionable"
            )
            continue
        if b["sessionText"] != expected:
            fail(
                f"{tag}: a toast for {what} paints the session line "
                f"{b['sessionText']!r}, not {expected!r}"
            )
        sb = b["sessionBox"]
        if not sb or not sb["painted"]:
            fail(
                f"{tag}: the toast session line for {what} is in the DOM but "
                f"paints no box ({sb}). A name nobody can see is not a name"
            )
        elif sb["w"] < 8 or sb["h"] < 6:
            fail(
                f"{tag}: the toast session line for {what} measured "
                f"{sb['w']}x{sb['h']}, too small to read"
            )
        if b["titleText"] != "Your turn":
            fail(
                f"{tag}: the toast title reads {b['titleText']!r}; the session "
                f"name leaked into the title instead of its own element"
            )

    page.evaluate("() => window.__reset()")
    page.evaluate("() => window.__toast({session_label: null, session_name: null})")
    b = measure(page, f"{tag}/toast-unknown", width)
    if b is None:
        return
    if not b["sessionPresent"]:
        fail(
            f"{tag}: a toast that cannot name its session renders no session "
            f"line at all. That reads as a toast about whatever the user is "
            f"looking at, which is the wrong session"
        )
    else:
        text = (b["sessionText"] or "").strip()
        if not text:
            fail(f"{tag}: the unknown-session line paints an empty string")
        elif "null" in text or "undefined" in text:
            fail(
                f"{tag}: the unknown-session line reads {text!r} - a "
                f"stringified null shown to a user"
            )
        elif "unknown" not in text.lower():
            fail(
                f"{tag}: a toast that cannot name its session says {text!r}, "
                f"which does not tell the reader it does not know"
            )
        sb = b["sessionBox"]
        if not sb or not sb["painted"]:
            fail(f"{tag}: the unknown-session line paints no box ({sb})")


def run_case(page, tag: str, width: int) -> None:
    ctrl = page.evaluate("() => window.__control()")
    if not ctrl.get("titleMoved"):
        undet(
            f"{tag}: the positive control could not move document.title. Every "
            f"tab-title verdict in this run would then be measuring a pinned "
            f"string, so none of them mean anything"
        )
        return
    if not ctrl.get("cardPainted"):
        undet(
            f"{tag}: the positive control painted no toast card. The sampler is "
            f"blind, so every 'the toast says X' verdict would pass while "
            f"measuring nothing"
        )
        return
    if measure(page, f"{tag}/control", width) is None:
        return
    check_tab_title(page, tag, width)
    check_toast(page, tag, width)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        print(
            f"CANNOT DETERMINE: playwright not importable ({exc}). Run with an "
            f"interpreter that has it."
        )
        return 2

    httpd, port = serve(ROOT)
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as exc:  # noqa: BLE001
                print(f"CANNOT DETERMINE: chromium would not launch ({exc})")
                return 2
            for vp_name, width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.add_init_script(collector_init_script())
                page.goto(f"http://127.0.0.1:{port}{HARNESS}")
                try:
                    page.wait_for_function(
                        "() => window.__surfacesReady === true", timeout=15000
                    )
                except Exception as exc:  # noqa: BLE001
                    undet(f"{vp_name}: harness never became ready ({exc})")
                    page.close()
                    continue
                run_case(page, vp_name, width)
                for v in violations(page):
                    undet(
                        f"{vp_name}: CSP violation on the harness ({v}). The "
                        f"page did not run as production would"
                    )
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
    print(
        f"PASS: the tab title and the toast session line both read the "
        f"session's LABEL, fall back to the tmux name without one, and say so "
        f"when neither exists - measured across {len(VIEWPORTS)} viewports"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

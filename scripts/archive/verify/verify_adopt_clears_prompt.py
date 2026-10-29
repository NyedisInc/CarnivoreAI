#!/usr/bin/env python3
"""Prove "adopt all" makes the attribution card STOP PAINTING.

WHAT IS REAL AND WHAT IS NOT. Real: the FastAPI route, the SQLite
database, the adoption write, client/js/launchpad.js, the shipped CSS,
Chromium. Not real: tmux, which is replaced by a synthetic listing
object. THIS SCRIPT NEVER OPENS A TMUX SOCKET, and in particular never
touches the user's live 'cloude' socket - the database it drives is a
throwaway under tempfile.

THE POSITIVE CONTROL IS THE BEFORE-READING. A rig that reports "nothing
is painted" and a rig that is simply broken produce identical output, so
the card is measured as a non-zero painted box BEFORE the click and the
two readings are compared. An empty result is only trusted from a rig
that has just been shown reporting a full one.

THREE OUTCOMES, and they exit differently:
  0  PASS              every assertion measured and held
  1  FAIL              something was measured and was wrong
  2  CANNOT DETERMINE  the measurement could not be taken at all
                       (playwright missing, chromium would not launch,
                       harness never became ready). Never a pass.

Run: python3 scripts/verify_adopt_clears_prompt.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp())
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp())
os.environ.setdefault("TOTP_SECRET", "harnessnotreal")
os.environ.setdefault("JWT_SECRET", "harnessnotreal")

from lib_adopt_clear_server import NAMES, Server  # noqa: E402
from lib_csp_static_server import serve  # noqa: E402

HARNESS = "/tests/manual/attribution-adopt-harness.html"
VIEWPORT = {"width": 430, "height": 900}


class Report:

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.lines: list[str] = []

    def check(self, ok: bool, name: str, detail: str = "") -> None:
        self.lines.append(
            ("PASS" if ok else "FAIL") + f": {name}" + (f"  [{detail}]" if detail else "")
        )
        if not ok:
            self.failures.append(name)


def _stable_report(page) -> dict:
    previous = None
    for _ in range(40):
        current = page.evaluate(
            """() => new Promise((resolve) => {
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    resolve(window.__attributionReport());
                }));
            })"""
        )
        if previous is not None:
            a, b = previous.get("slotBox"), current.get("slotBox")
            same = (a is None and b is None) or (
                a is not None
                and b is not None
                and abs(a["height"] - b["height"]) < 0.5
            )
            if same and previous.get("slotHtmlLength") == current.get(
                "slotHtmlLength"
            ):
                return current
        previous = current
    raise RuntimeError("the harness geometry never settled across two frames")


def _settle_after_click(page, adopts: int, declines: int = 0) -> None:
    """Wait for the click's SERVER CALLS to finish, then let the DOM settle.

    Description: waiting on the outcome instead - "the rows are gone" -
      would make a server that never clears them time out and report
      CANNOT DETERMINE, when what actually happened is a measurable
      FAIL. So this waits only for the calls the click makes, which
      happen either way, and leaves the verdict to the pixel assertions.

      IT WAITS IN THE PAGE, NOT IN PYTHON. A poll loop on this thread
      cannot service the Playwright bindings the page is waiting on, so
      the very calls being waited for could never arrive - the first
      version of this function deadlocked after exactly one adopt.
    Inputs: page - the Playwright page. adopts (int) - adoption calls to
      expect. declines (int) - declined names to expect. The page must
      have fetched the prompt exactly once before the click.
    Output: None.
    Raises: playwright TimeoutError - the calls never happened, which IS
      a genuine could-not-evaluate.
    """
    page.wait_for_function(
        "([a, d]) => window.__calls.adopts >= a && window.__calls.declines >= d",
        arg=[adopts, declines],
        timeout=15000,
    )
    page.wait_for_function(
        "() => window.__calls.prompts >= 2", timeout=15000
    )
    _stable_report(page)


def _assert_measurable(rep: Report, data: dict, label: str) -> bool:
    vp = data["viewport"]
    ok_hidden = vp["hidden"] is False
    ok_width = vp["innerWidth"] == VIEWPORT["width"]
    rep.check(
        ok_hidden,
        f"{label}: the tab is VISIBLE, so a rect is a real rect",
        f"hidden={vp['hidden']} visibilityState={vp['visibilityState']}",
    )
    rep.check(
        ok_width,
        f"{label}: the viewport is the one that was asked for",
        f"innerWidth={vp['innerWidth']} expected={VIEWPORT['width']}",
    )
    return ok_hidden and ok_width


def _painted(data: dict) -> float:
    slot = data.get("slotBox")
    if not slot:
        return 0.0
    return float(slot["width"]) * float(slot["height"])


def _bind(page, server: Server) -> None:
    page.expose_binding("__srvPrompt", lambda _src: server.prompt())
    page.expose_binding("__srvAdopt", lambda _src, name: server.adopt(name))
    page.expose_binding("__srvDecline", lambda _src, names: server.decline(names))


def measure_adopt_all(browser, port, rep: Report) -> None:
    state = Path(tempfile.mkdtemp())
    server = Server(state)
    server.seed()
    page = browser.new_page(viewport=VIEWPORT)
    _bind(page, server)
    page.goto(f"http://127.0.0.1:{port}{HARNESS}")
    page.wait_for_function("() => window.__attributionReady === true", timeout=15000)
    try:
        before = _stable_report(page)
        if not _assert_measurable(rep, before, "adopt-all/before"):
            return

        rep.check(
            before["card"] is not None and before["card"]["nonZeroBox"],
            "adopt-all/before: the card has a NON-ZERO painted box",
            f"{_painted(before):.0f} sq px",
        )
        rep.check(
            sorted(before["rowNames"]) == sorted(NAMES),
            "adopt-all/before: every unattributed session is itemised",
            str(before["rowNames"]),
        )

        rep.check(page.evaluate("() => window.__clickAdoptAll()"),
                  "adopt-all: the 'adopt all' button exists and was clicked")
        # CANNOT DETERMINE
        # could not
        _settle_after_click(page, len(NAMES))
        after = _stable_report(page)
        if not _assert_measurable(rep, after, "adopt-all/after"):
            return

        rep.check(
            _painted(after) == 0.0,
            "adopt-all/after: the prompt paints ZERO pixels",
            f"{_painted(after):.0f} sq px (was {_painted(before):.0f})",
        )
        rep.check(
            after["card"] is None,
            "adopt-all/after: no card element exists at all",
            str(after["cardState"]),
        )
        rep.check(
            after["slotHtmlLength"] == 0,
            "adopt-all/after: the slot is empty",
            f"slotHtmlLength={after['slotHtmlLength']}",
        )
        rep.check(
            not after["errorText"],
            "adopt-all/after: no error was shown, because none occurred",
            str(after["errorText"]),
        )
        origins = server.origins()
        rep.check(
            all(origins.get(n) == "adopted" for n in NAMES),
            "adopt-all: every row really is origin='adopted'",
            str(origins),
        )
    finally:
        page.close()


def measure_adopt_picked(browser, port, rep: Report) -> None:
    state = Path(tempfile.mkdtemp())
    server = Server(state)
    server.seed()
    page = browser.new_page(viewport=VIEWPORT)
    _bind(page, server)
    page.goto(f"http://127.0.0.1:{port}{HARNESS}")
    page.wait_for_function("() => window.__attributionReady === true", timeout=15000)
    try:
        before = _stable_report(page)
        if not _assert_measurable(rep, before, "adopt-picked/before"):
            return
        rep.check(page.evaluate("() => window.__clickChoose()"),
                  "adopt-picked: 'choose individually' was clicked")
        rep.check(
            page.evaluate("(n) => window.__setRow(n, false)", NAMES[2]),
            f"adopt-picked: {NAMES[2]} was unticked",
        )
        rep.check(page.evaluate("() => window.__clickAdoptPicked()"),
                  "adopt-picked: 'adopt the ticked ones' was clicked")
        _settle_after_click(page, 2)
        after = _stable_report(page)
        if not _assert_measurable(rep, after, "adopt-picked/after"):
            return
        rep.check(
            after["card"] is not None and after["card"]["nonZeroBox"],
            "adopt-picked/after: the card still PAINTS, with the rest",
            f"{_painted(after):.0f} sq px",
        )
        rep.check(
            after["rowNames"] == [NAMES[2]],
            "adopt-picked/after: only the unticked session is still asked about",
            str(after["rowNames"]),
        )
        rep.check(
            _painted(after) < _painted(before),
            "adopt-picked/after: the card is visibly SMALLER than it was",
            f"{_painted(after):.0f} < {_painted(before):.0f} sq px",
        )
    finally:
        page.close()


def measure_decline_all(browser, port, rep: Report) -> None:
    state = Path(tempfile.mkdtemp())
    server = Server(state)
    server.seed()
    page = browser.new_page(viewport=VIEWPORT)
    _bind(page, server)
    page.goto(f"http://127.0.0.1:{port}{HARNESS}")
    page.wait_for_function("() => window.__attributionReady === true", timeout=15000)
    try:
        before = _stable_report(page)
        if not _assert_measurable(rep, before, "decline-all/before"):
            return
        rep.check(
            before["card"] is not None and before["card"]["nonZeroBox"],
            "decline-all/before: the card has a NON-ZERO painted box",
            f"{_painted(before):.0f} sq px",
        )
        rep.check(page.evaluate("() => window.__clickDeclineAll()"),
                  "decline-all: the 'leave as external' button was clicked")
        _settle_after_click(page, 0, declines=len(NAMES))
        after = _stable_report(page)
        if not _assert_measurable(rep, after, "decline-all/after"):
            return
        rep.check(
            _painted(after) == 0.0,
            "decline-all/after: the prompt paints ZERO pixels",
            f"{_painted(after):.0f} sq px (was {_painted(before):.0f})",
        )
        rep.check(
            not after["errorText"],
            "decline-all/after: no error was shown",
            str(after["errorText"]),
        )
    finally:
        page.close()


def main() -> int:
    """Serve the repo, drive the harness in a real browser, print results.

    Output: int - 0 pass, 1 fail, 2 could not evaluate.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "CANNOT DETERMINE: playwright is not importable, so no pixel was "
            "measured."
        )
        print(
            "  install with: python3 -m pip install playwright && "
            "python3 -m playwright install chromium"
        )
        return 2

    httpd, port = serve(ROOT)
    rep = Report()
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as exc:  # noqa: BLE001
                print(f"CANNOT DETERMINE: chromium would not launch: {exc}")
                return 2
            try:
                rep.lines.append("--- adopt all ---")
                measure_adopt_all(browser, port, rep)
                rep.lines.append("--- adopt the ticked ones ---")
                measure_adopt_picked(browser, port, rep)
                rep.lines.append("--- leave as external ---")
                measure_decline_all(browser, port, rep)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        print("\n".join(rep.lines))
        print(f"CANNOT DETERMINE: the measurement run did not complete: {exc}")
        return 2
    finally:
        httpd.shutdown()

    print("\n".join(rep.lines))
    if rep.failures:
        print(f"\nFAILED {len(rep.failures)} check(s):")
        for f in rep.failures:
            print(f"  - {f}")
        return 1
    print(
        f"\nALL PASS ({sum(1 for line in rep.lines if line.startswith('PASS'))} "
        "measured checks)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

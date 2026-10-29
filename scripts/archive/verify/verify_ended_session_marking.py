#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = "/tests/manual/ended-sessions-harness.html"

VIEWPORT = {"width": 1280, "height": 900}

THEMES = ("claude", "terminal")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_csp_static_server import serve  # noqa: E402


class Report:

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.blocked: list[str] = []
        self.lines: list[str] = []

    def ok(self, msg: str) -> None:
        self.lines.append(f"  PASS  {msg}")

    def fail(self, msg: str) -> None:
        self.failures.append(msg)
        self.lines.append(f"  FAIL  {msg}")

    def cannot(self, msg: str) -> None:
        self.blocked.append(msg)
        self.lines.append(f"  CANNOT DETERMINE  {msg}")

    def check(self, condition: bool, msg: str) -> None:
        self.ok(msg) if condition else self.fail(msg)

    def control(self, condition: bool, msg: str) -> None:
        self.ok(f"control: {msg}") if condition else self.cannot(
            f"control did not hold, so nothing measured beside it can be "
            f"trusted: {msg}"
        )


def _visible(box: dict | None) -> bool:
    if not box:
        return False
    return (
        box["width"] > 0
        and box["height"] > 0
        and box["display"] != "none"
        and box["visibility"] != "hidden"
    )


def measure_theme(page, base: str, theme: str, report: Report) -> None:
    page.goto(f"{base}{HARNESS}?theme={theme}", wait_until="load")
    page.wait_for_function("() => window.__endedReady === true", timeout=15000)

    if page.evaluate("() => document.hidden"):
        report.cannot(f"[{theme}] the tab is hidden; geometry would be unreliable")
        return
    if not page.evaluate("() => window.__themeApplied === true"):
        report.cannot(f"[{theme}] the theme manifest did not apply")
        return

    data = page.evaluate("() => window.__endedReport()")
    label = f"[{theme}]"

    report.control(
        _visible(data["liveRow"]),
        f"{label} the LIVE row renders with real pixels "
        f"(so a missing ended row means something)",
    )
    if not _visible(data["liveRow"]):
        return

    report.check(
        _visible(data["endedRow"]),
        f"{label} the ENDED row renders with real pixels "
        f"(name={data['endedRowName']}, h={_h(data['endedRow'])})",
    )
    report.check(
        _visible(data["endedBadge"]),
        f"{label} the ENDED badge occupies a real box "
        f"({_wh(data['endedBadge'])})",
    )
    badge_text = (data["endedBadge"] or {}).get("text", "")
    report.check(
        badge_text.strip().upper() == "ENDED",
        f"{label} the badge says ENDED in words, not by colour alone "
        f"(text={badge_text!r})",
    )
    report.check(
        (data["endedBadge"] or {}).get("color")
        != (data["endedBadge"] or {}).get("backgroundColor"),
        f"{label} the badge text is not the same colour as its own "
        f"background (the ~~claude class of defect)",
    )

    report.check(
        _visible(data["endedDot"]),
        f"{label} the stopped status dot occupies a real box "
        f"({_wh(data['endedDot'])})",
    )
    ended_dot = data["endedDot"] or {}
    live_dot = data["liveDot"] or {}
    same_colour = ended_dot.get("backgroundColor") == live_dot.get("backgroundColor")
    same_opacity = ended_dot.get("opacity") == live_dot.get("opacity")
    report.check(
        not (same_colour and same_opacity),
        f"{label} the ended dot is DISTINGUISHABLE from the live/idle dot "
        f"(ended: bg={ended_dot.get('backgroundColor')} "
        f"opacity={ended_dot.get('opacity')}; "
        f"live: bg={live_dot.get('backgroundColor')} "
        f"opacity={live_dot.get('opacity')})",
    )

    report.check(
        data["endedRowCursor"] != "pointer",
        f"{label} the ended row does not present a pointer cursor "
        f"(cursor={data['endedRowCursor']})",
    )
    report.check(
        data["endedRowHasButtonRole"] is False,
        f"{label} the ended row carries no button role",
    )
    attach_calls = page.evaluate("() => window.__clickEndedRowBody()")
    report.check(
        attach_calls == [],
        f"{label} clicking the ended row's body attaches to NOTHING "
        f"(attempts={attach_calls})",
    )

    report.check(
        "cloude_deleted" not in data["treeNames"],
        f"{label} the DELETED session appears nowhere in the tree "
        f"(rendered={data['treeNames']})",
    )
    report.check(
        "cloude_media" in data["treeNames"],
        f"{label} the ENDED session DOES appear - this is the reported bug "
        f"(rendered={data['treeNames']})",
    )

    report.check(
        _visible(data["recentDot"]),
        f"{label} RECENT renders the SAME stopped dot, not a second "
        f"vocabulary ({_wh(data['recentDot'])})",
    )
    report.check(
        _visible(data["recentDeleteBtn"]),
        f"{label} RECENT offers a visible delete control "
        f"({_wh(data['recentDeleteBtn'])})",
    )

    report.check(
        _visible(data["deleteBtn"]) and _visible(data["restartBtn"]),
        f"{label} the ended row's delete and restart controls occupy real "
        f"boxes (delete={_wh(data['deleteBtn'])}, "
        f"restart={_wh(data['restartBtn'])})",
    )
    if _visible(data["deleteBtn"]):
        page.click(".project-session-row--ended .ended-session-delete")
        page.wait_for_timeout(250)
        after = page.evaluate("() => window.__endedReport()")
        report.check(
            after["deleteCalls"] == ["u-ended"],
            f"{label} the delete control calls DELETE for the row's own "
            f"uuid, not its tmux name (calls={after['deleteCalls']})",
        )
        report.check(
            "cloude_media" not in after["treeNames"],
            f"{label} the row leaves the tree once deleted "
            f"(rendered={after['treeNames']})",
        )


def _wh(box: dict | None) -> str:
    if not box:
        return "ABSENT"
    return f"{box['width']:.1f}x{box['height']:.1f}"


def _h(box: dict | None) -> str:
    return "ABSENT" if not box else f"{box['height']:.1f}"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("CANNOT DETERMINE: playwright is not importable, so no pixels "
              "were measured.")
        print("  install with: python3 -m pip install playwright && "
              "python3 -m playwright install chromium")
        return 2

    report = Report()
    server, port = serve(ROOT)
    base = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as exc:
                print(f"CANNOT DETERMINE: chromium would not launch: {exc}")
                return 2
            try:
                context = browser.new_context(viewport=VIEWPORT)
                page = context.new_page()
                for theme in THEMES:
                    print(f"\n--- theme: {theme} ---")
                    try:
                        measure_theme(page, base, theme, report)
                    except Exception as exc:
                        report.cannot(f"[{theme}] the harness never settled: {exc}")
                    for line in report.lines:
                        print(line)
                    report.lines = []
            finally:
                browser.close()
    finally:
        server.shutdown()

    print()
    if report.blocked:
        print(f"CANNOT DETERMINE ({len(report.blocked)}):")
        for line in report.blocked:
            print(f"  - {line}")
        return 2
    if report.failures:
        print(f"FAIL ({len(report.failures)}):")
        for line in report.failures:
            print(f"  - {line}")
        return 1
    print(f"PASS - every assertion measured and held across {len(THEMES)} themes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

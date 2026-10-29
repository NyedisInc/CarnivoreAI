#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

from playwright.sync_api import sync_playwright

HARNESS = "http://127.0.0.1:5011/tests/manual/copy-output-harness.html"

CHROME_BIN = os.environ.get("COPY_OUTPUT_CHROME")

FULL_URL = (
    "https://claude.ai/oauth/authorize?code=true&client_id=9d1c3f7a"
    "&scope=user%3Ainference&state=abcdef0123456789"
)

COPY_SPY = """
() => {
    window.__copyEvents = [];
    document.addEventListener('copy', (e) => {
        let payload = null;
        try { payload = e.clipboardData.getData('text/plain'); } catch (x) { payload = 'ERR'; }
        window.__copyEvents.push({
            payload: payload,
            selLen: window.getSelection().toString().length,
            prevented: e.defaultPrevented,
        });
    }, false);
}
"""


class CheckFailed(AssertionError):
    pass


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"ok   - {name}")
        return
    print(f"FAIL - {name} {detail}")
    raise CheckFailed(name)


def main() -> int:
    with sync_playwright() as pw:
        launch_args = {"executable_path": CHROME_BIN} if CHROME_BIN else {}
        browser = pw.chromium.launch(args=["--use-mock-keychain"], **launch_args)
        context = browser.new_context(
            viewport={"width": 375, "height": 812},
            has_touch=True,
            is_mobile=True,
        )
        page = context.new_page()
        page.goto(HARNESS)

        page.click("#dropBtn")
        check(
            "clipboard api is gone",
            page.evaluate("() => window.CopyCompat.hasAsyncClipboard()") is False,
        )

        page.click("#narrowBtn")
        page.evaluate(COPY_SPY)
        page.click("#openBtn")

        chip_value = page.get_attribute(".cloude-copy-chip--url", "data-value")
        check(
            "wrapped url is rejoined, not cut at the pane width",
            chip_value == FULL_URL,
            f"got {chip_value!r}",
        )

        label = page.inner_text(".cloude-copy-chip--url .cloude-copy-chip__value")
        check(
            "chip label is shortened for the narrow screen",
            len(label) < len(FULL_URL) and "..." in label,
            f"got {label!r}",
        )

        page.tap(".cloude-copy-chip--url")
        page.wait_for_timeout(200)

        events = page.evaluate("() => window.__copyEvents")
        check("a copy event was raised", len(events) == 1, f"got {events!r}")
        check(
            "the FULL url reached the clipboard, not the shortened label",
            events[0]["payload"] == FULL_URL,
            f"got {events[0]['payload']!r}",
        )
        check(
            "the selection was real, not empty (the original bug)",
            events[0]["selLen"] > 0,
            f"selLen {events[0]['selLen']}",
        )

        status = page.inner_text(".cloude-copy-status")
        check(
            "the tap reports success inside the sheet",
            "copied url" in status,
            f"got {status!r}",
        )
        check(
            "the tapped chip itself shows a copied state",
            "is-copied" in (page.get_attribute(".cloude-copy-chip--url", "class") or ""),
        )
        check(
            "the sheet stays open so the code can be copied too",
            page.is_visible(".cloude-copy-sheet"),
        )

        page.evaluate("() => { window.__copyEvents = []; }")
        page.tap(".cloude-copy-chip--code")
        page.wait_for_timeout(200)
        events = page.evaluate("() => window.__copyEvents")
        check(
            "the sign-in code copies whole",
            len(events) == 1 and events[0]["payload"] == "WDJB-MJHT",
            f"got {events!r}",
        )

        page.evaluate("() => { document.execCommand = () => false; }")
        page.evaluate("() => { window.__copyEvents = []; }")
        page.tap(".cloude-copy-chip--url")
        page.wait_for_timeout(200)
        status = page.inner_text(".cloude-copy-status")
        check(
            "an impossible copy says so instead of claiming success",
            "blocked" in status,
            f"got {status!r}",
        )
        selected = page.evaluate(
            """() => {
                const t = document.querySelector('.cloude-copy-sheet__text');
                return t.value.slice(t.selectionStart, t.selectionEnd);
            }"""
        )
        check(
            "the failed token is left selected for a manual copy",
            selected == FULL_URL,
            f"got {selected!r}",
        )

        page.screenshot(path="/tmp/copy-output-mobile.png", full_page=False)
        browser.close()
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CheckFailed:
        sys.exit(1)

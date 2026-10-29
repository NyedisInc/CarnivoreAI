
from __future__ import annotations

import http.server
import os
import socket
import socketserver
import threading
from pathlib import Path

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so NOTHING about the restart "
        "picker's arm box or danger button was measured. This is a "
        "could-not-evaluate, not a pass."
    ),
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_ROOT = REPO_ROOT / "client"

DESKTOP = {"width": 1280, "height": 900}
EPSILON_PX = 0.5

CSS_FILES = [
    "css/styles.css",
    "css/modal-titlerow.css",
    "css/session-restart-picker.css",
    "dist/app.css",
]

JS_FILES = [
    "js/session-status-ui.js",
    "js/session-restart-live.js",
    "js/session-restart-options.js",
    "js/session-restart-picker.js",
]

PREVIEW_ALIVE = {
    "name": "test-session",
    "current_agent_type": "claude",
    "pane_state": "alive",
    "unchanged": {
        "kind": "agent",
        "detail": "resume the same conversation in the same pane",
        "command": None,
        "actionable": False,
        "conversation": "resumed",
    },
    "projected": {
        "kind": "agent",
        "detail": "resume the same conversation in the same pane",
        "command": None,
        "actionable": False,
        "conversation": "resumed",
    },
    "options": [],
    "wrappers_status": "ok",
}

HARNESS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
__CSS__
</head>
<body>
__JS__
<script>
window.__preview = null;
window.API = {
  restartPreview: function () { return Promise.resolve(window.__preview); },
};
window.App = {
  showConfirmModal: function () { return Promise.resolve(false); },
};
window.__open = function (preview) {
  window.__preview = preview;
  window.SessionRestartPicker.open('row-alive', 'Test Session', null);
};
</script>
</body>
</html>
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _ClientHandler(http.server.SimpleHTTPRequestHandler):

    def translate_path(self, path: str) -> str:  # noqa: D102
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/static/"):
            return str(CLIENT_ROOT / clean[len("/static/"):])
        return str(CLIENT_ROOT / clean.lstrip("/"))

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] in ("/", "/index.html"):
            body = _harness_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args) -> None:  # noqa: D102
        return


def _harness_html() -> str:
    css = "\n".join(
        f'<link rel="stylesheet" href="/static/{name}">' for name in CSS_FILES
    )
    js = "\n".join(f'<script src="/static/{name}"></script>' for name in JS_FILES)
    js += '\n<script type="module" src="/static/js/i18n/boot.js"></script>'
    js += '\n<script type="module" src="/static/dist/app.js"></script>'
    return HARNESS_HTML.replace("__CSS__", css).replace("__JS__", js)


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), _ClientHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def measurement(base_url):
    from playwright.sync_api import sync_playwright

    headed = os.environ.get("CLOUDE_TEST_HEADED") == "1"
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=not headed, args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(
                f"chromium could not launch ({exc}), so NOTHING about the "
                "restart picker's arm box or danger button was measured. "
                "Not a pass."
            )
        context = browser.new_context(viewport=DESKTOP, device_scale_factor=1)
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base_url, wait_until="load")
        assert page.evaluate("document.hidden") is False, (
            "the page reports document.hidden; a backgrounded tab freezes "
            "its render loop and every measurement below would be "
            "manufactured"
        )
        assert page.evaluate("!!window.SessionRestartPicker"), (
            "session-restart-picker.js did not load"
        )
        page.evaluate("p => window.__open(p)", PREVIEW_ALIVE)
        page.wait_for_selector("#restart-picker-live", state="visible")

        def _wait_for_stable_arm_rect(stable_reads=3, interval_ms=80, timeout_ms=3000):
            last = None
            streak = 0
            deadline_ms = 0
            while deadline_ms < timeout_ms:
                rect = page.evaluate(
                    """() => {
                        const r = document.querySelector(
                            '.restart-picker__arm').getBoundingClientRect();
                        return {top: r.top, left: r.left,
                                width: r.width, height: r.height};
                    }"""
                )
                if last is not None and all(
                    abs(rect[k] - last[k]) <= 0.05 for k in rect
                ):
                    streak += 1
                    if streak >= stable_reads:
                        return rect
                else:
                    streak = 0
                last = rect
                page.wait_for_timeout(interval_ms)
                deadline_ms += interval_ms
            pytest.fail(
                f"the arm row never settled within {timeout_ms}ms "
                f"(last rect: {last}); cannot measure a moving target"
            )

        def _snapshot():
            return page.evaluate(
                """() => {
                    const arm = document.querySelector('.restart-picker__arm');
                    const go = document.querySelector('#restart-picker-go');
                    const box = el => {
                        const r = el.getBoundingClientRect();
                        return {top: r.top, left: r.left,
                                width: r.width, height: r.height};
                    };
                    // color-mix() serialises getComputedStyle in its OWN
                    // mixing space ('oklab(...)'), not rgb() - a canvas is
                    // the one thing that normalises rgb(), oklab() and
                    // color(srgb ...) alike to concrete sRGB bytes, same
                    // technique test_style_guide_themes.py's contrast probe
                    // uses for the same reason (issue #652).
                    const ctx = document.createElement('canvas')
                        .getContext('2d', { willReadFrequently: true });
                    const toRgb = (css) => {
                        ctx.clearRect(0, 0, 1, 1);
                        ctx.fillStyle = '#000';
                        ctx.fillStyle = css;
                        ctx.fillRect(0, 0, 1, 1);
                        const d = ctx.getImageData(0, 0, 1, 1).data;
                        return `rgb(${d[0]}, ${d[1]}, ${d[2]})`;
                    };
                    const cs = el => {
                        const c = getComputedStyle(el);
                        return {
                            background: toRgb(c.backgroundColor),
                            borderColor: toRgb(c.borderTopColor),
                        };
                    };
                    return {
                        armRect: box(arm),
                        armStyle: cs(arm),
                        goClasses: go.className,
                        goDisabled: go.disabled,
                        goStyle: cs(go),
                    };
                }"""
            )

        _wait_for_stable_arm_rect()
        before = _snapshot()
        page.click("#restart-picker-live")
        _wait_for_stable_arm_rect()
        after = _snapshot()
        assert not errors, f"the page threw: {errors}"
        context.close()
        browser.close()
    return {"before": before, "after": after}


def test_checking_the_arm_box_does_not_move_or_repaint_its_row(measurement):
    before_rect = measurement["before"]["armRect"]
    after_rect = measurement["after"]["armRect"]
    for field in ("top", "left", "width", "height"):
        assert abs(before_rect[field] - after_rect[field]) <= EPSILON_PX, (
            f"the arm row's {field} moved from {before_rect[field]} to "
            f"{after_rect[field]} when the checkbox was ticked; the row "
            "must hold still"
        )
    before_bg = measurement["before"]["armStyle"]["background"]
    after_bg = measurement["after"]["armStyle"]["background"]
    assert after_bg == before_bg, (
        f"the arm row's background changed from {before_bg!r} to "
        f"{after_bg!r} when the checkbox was ticked; checking the box "
        "must not fill the row with the danger colour"
    )


def test_armed_kill_button_is_dark_interior_bright_outline(measurement):
    after = measurement["after"]
    assert after["goDisabled"] is False, (
        "the kill-and-restart button is still disabled once the arm box "
        "is ticked and a pickable choice is selected"
    )
    classes = after["goClasses"].split()
    assert "modal-btn-danger" in classes, (
        f"armed button classes are {classes!r}; expected the shared "
        "destructive style .modal-btn-danger"
    )
    assert "modal-btn-primary" not in classes, (
        f"armed button classes are {classes!r}; the plain confirm style "
        ".modal-btn-primary must not still be applied once armed"
    )
    style = after["goStyle"]
    assert style["background"] == "rgb(95, 57, 56)", (
        f"armed button background is {style['background']!r}, expected "
        "the token-derived dark red interior rgb(95, 57, 56), not a "
        "bright solid fill"
    )
    assert style["borderColor"] == "rgb(255, 68, 68)", (
        f"armed button border is {style['borderColor']!r}, expected the "
        "bright red outline rgb(255, 68, 68) (#ff4444)"
    )

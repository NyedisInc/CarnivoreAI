
from __future__ import annotations

import http.server
import socket
import socketserver
import threading
from pathlib import Path

import pytest

from tests.helpers.focus_edge import assert_focus_edge, measure_focus_edge

pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so NOTHING about how the text-prompt "
        "modal renders was measured. This is a could-not-evaluate, not a "
        "pass."
    ),
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_ROOT = REPO_ROOT / "client"

CSS_FILES = [
    "dist/app.css",
    "css/styles.css",
    "css/modal-titlerow.css",
    "css/session-restart-picker.css",
    "css/text-prompt-modal.css",
    "dist/app.css",
]

JS_FILES = [
    "js/modal-stack.js",
    "js/text-prompt-modal.js",
]

HARNESS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
__CSS__
<style>
  :root {
    --color-bg: #1e1e1e; --color-bg-hover: #2c2c2c; --color-bg-elevated: #262626;
    --color-fg: #ddd; --color-fg-strong: #fff; --color-fg-subtle: #999;
    --color-accent: #7aa2f7; --color-border: #444; --color-border-subtle: #3a3a3a;
    --color-danger: #c0392b;
    --radius-sm: 3px; --radius-md: 6px;
  }
  html, body { margin: 0; background: var(--color-bg); color: var(--color-fg); }
</style>
</head>
<body>
__JS__
<!-- A REAL restart-picker cancel/danger button pair, off-screen, so the
     comparison tests below read their ACTUAL shipped computed style rather
     than a hand copy of session-restart-picker.css's rules. -->
<div class="restart-picker" style="position: fixed; top: -9999px; left: -9999px;">
  <button type="button" class="modal-btn modal-btn-secondary" id="__ref-cancel">cancel</button>
  <button type="button" class="modal-btn modal-btn-danger" id="__ref-danger">kill and restart</button>
</div>
<script>
window.__open = function (opts) {
  window.__result = 'pending';
  window.TextPromptModal.open(opts).then(function (r) { window.__result = r; });
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


@pytest.fixture()
def page(base_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(
                f"chromium could not launch ({exc}), so NOTHING about how "
                "the text-prompt modal renders was measured. Not a pass."
            )
        context = browser.new_context(viewport={"width": 1024, "height": 768})
        pg = context.new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base_url, wait_until="load")
        assert pg.evaluate("document.hidden") is False, (
            "the page reports document.hidden; a backgrounded tab freezes its "
            "render loop and every measurement below would be manufactured"
        )
        assert pg.evaluate("!!window.TextPromptModal"), (
            "text-prompt-modal.js did not load"
        )
        assert not errors, f"the page threw while loading: {errors}"
        try:
            yield pg
        finally:
            context.close()
            browser.close()


_OPTS = {
    "title": "new group",
    "label": "group name",
    "placeholder": "e.g. research",
    "confirmLabel": "create",
    "cancelLabel": "cancel",
}


def _open(page) -> None:
    page.evaluate("opts => window.__open(opts)", _OPTS)
    page.wait_for_selector(".text-prompt-modal__head", state="visible")


def test_title_row_replaces_the_plain_header(page):
    _open(page)
    measured = page.evaluate(
        """() => ({
            headExists: !!document.querySelector('.text-prompt-modal__head'),
            verbText: (document.querySelector('.text-prompt-modal__verb') || {})
                .textContent,
            oldHeaderGone: !document.querySelector('.modal-header'),
        })"""
    )
    assert measured["headExists"], measured
    assert measured["oldHeaderGone"], measured
    assert measured["verbText"].strip() == "» new group", measured


def _token(page, name: str) -> str:
    return page.evaluate(
        """name => {
            const probe = document.createElement('span');
            probe.style.color = `var(${name})`;
            document.body.appendChild(probe);
            const out = getComputedStyle(probe).color;
            probe.remove();
            return out;
        }""",
        name,
    )


_TRANSPARENT = ("rgba(0, 0, 0, 0)", "transparent")


def test_verb_and_confirm_edge_follow_the_theme_accent(page):
    _open(page)

    def _measure(accent: str) -> dict:
        page.evaluate(
            "hex => document.documentElement.style.setProperty("
            "'--color-accent', hex)",
            accent,
        )
        page.wait_for_timeout(300)
        return page.evaluate(
            """() => ({
                verb: getComputedStyle(
                    document.querySelector('.text-prompt-modal__verb')
                ).color,
                confirmEdge: getComputedStyle(
                    document.querySelector('#text-prompt-modal-confirm')
                ).borderTopColor,
            })"""
        )

    first = _measure("#38bdf8")
    second = _measure("#facc15")

    for key in ("verb", "confirmEdge"):
        assert first[key] != second[key], (
            f"{key} did not change with --color-accent: {first} vs {second}. "
            "It is reading a literal, not a theme token."
        )


def test_buttons_have_no_corner_bracket_ornament(page):
    _open(page)
    for sel in ("#text-prompt-modal-confirm", "#text-prompt-modal-cancel"):
        m = page.evaluate(
            """sel => {
                const b = document.querySelector(sel);
                const before = getComputedStyle(b, '::before').content;
                const after = getComputedStyle(b, '::after').content;
                return {before, after};
            }""",
            sel,
        )
        assert m["before"] == "none", (sel, m)
        assert m["after"] == "none", (sel, m)


def test_cancel_matches_the_pickers_cancel_exactly(page):
    _open(page)
    m = page.evaluate(
        """() => {
            const cs = el => {
                const c = getComputedStyle(el);
                return {
                    background: c.backgroundColor,
                    border: c.borderTopColor,
                    borderWidth: c.borderTopWidth,
                    radius: c.borderTopLeftRadius,
                    paddingTop: c.paddingTop,
                    paddingLeft: c.paddingLeft,
                    fontSize: c.fontSize,
                    transform: c.textTransform,
                };
            };
            return {
                dialog: cs(document.querySelector('#text-prompt-modal-cancel')),
                picker: cs(document.querySelector('#__ref-cancel')),
            };
        }"""
    )
    assert m["dialog"] == m["picker"], m


def test_confirm_matches_the_dangers_shape_in_the_confirm_token(page):
    _open(page)
    m = page.evaluate(
        """() => {
            const cs = el => {
                const c = getComputedStyle(el);
                return {
                    background: c.backgroundColor,
                    border: c.borderTopColor,
                    borderWidth: c.borderTopWidth,
                    radius: c.borderTopLeftRadius,
                    paddingTop: c.paddingTop,
                    paddingLeft: c.paddingLeft,
                    fontSize: c.fontSize,
                    transform: c.textTransform,
                };
            };
            const confirm = document.querySelector('#text-prompt-modal-confirm');
            return {
                classes: Array.from(confirm.classList),
                confirm: cs(confirm),
                danger: cs(document.querySelector('#__ref-danger')),
            };
        }"""
    )
    assert "modal-btn-confirm" in m["classes"], m
    assert "modal-btn-primary" not in m["classes"], m
    assert "modal-btn-danger" not in m["classes"], m
    for key in ("borderWidth", "radius", "paddingTop", "paddingLeft",
                "fontSize", "transform"):
        assert m["confirm"][key] == m["danger"][key], (key, m)
    assert m["confirm"]["background"] in _TRANSPARENT, (
        f"the confirm button has a fill ({m}); it is an outline so a theme whose accent and danger "
        "hues are twins still tells it from the tinted destructive button by shape"
    )
    assert m["confirm"]["background"] != m["danger"]["background"], (
        "the confirm button must use the accent/confirm token, not the "
        f"same colour as the destructive style: {m}"
    )
    assert m["confirm"]["border"] != m["danger"]["border"], m
    assert m["confirm"]["border"] == _token(page, "--oc-orange"), m


def test_secondary_is_a_quiet_outline_that_never_takes_the_accent(page):
    _open(page)
    measured = page.evaluate(
        """() => {
            const cs = getComputedStyle(
                document.querySelector('#text-prompt-modal-cancel'));
            return {background: cs.backgroundColor, edge: cs.borderTopColor,
                    edgeWidth: cs.borderTopWidth, text: cs.color};
        }"""
    )
    assert measured["background"] in _TRANSPARENT, measured
    assert measured["edgeWidth"] == "1px", measured
    assert measured["edge"] == _token(page, "--oc-line-rule"), measured
    assert measured["text"] == _token(page, "--oc-text-secondary"), measured
    assert measured["text"] != _token(page, "--oc-orange"), measured


def test_field_is_a_hairline_whose_own_edge_lights_on_focus(page):
    _open(page)
    page.wait_for_timeout(250)
    rest = page.evaluate(
        """() => {
            const cs = getComputedStyle(document.querySelector('#text-prompt-modal-input'));
            return {radius: cs.borderTopLeftRadius, size: cs.fontSize};
        }"""
    )
    assert rest["radius"] == "2px", rest
    assert rest["size"] == "13px", rest
    m = measure_focus_edge(page, "#text-prompt-modal-input", how="click")
    assert m["rest"]["edgeWidth"] == "1px", m
    assert m["rest"]["edge"] == _token(page, "--oc-line-rule"), m
    assert m["rest"]["shadow"] == "none", m
    assert_focus_edge(m, "field")
    assert m["focus"]["edge"] != _token(page, "--oc-orange"), m


def test_enter_submits_escape_and_cancel_answer_null(page):
    _open(page)
    page.wait_for_timeout(250)
    page.keyboard.type("research")
    page.keyboard.press("Enter")
    page.wait_for_function("window.__result !== 'pending'")
    assert page.evaluate("window.__result") == "research"
    assert page.evaluate("!document.querySelector('.text-prompt-modal')")

    _open(page)
    page.keyboard.press("Escape")
    page.wait_for_function("window.__result !== 'pending'")
    assert page.evaluate("window.__result") is None

    _open(page)
    page.click("#text-prompt-modal-cancel")
    page.wait_for_function("window.__result !== 'pending'")
    assert page.evaluate("window.__result") is None

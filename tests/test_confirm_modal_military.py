
from __future__ import annotations

import http.server
import socket
import socketserver
import threading
from pathlib import Path

import pytest

from tests.helpers.focus_edge import assert_focus_edge, measure_focus_edge, settle_transitions

pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so NOTHING about how any confirm "
        "dialog renders was measured. This is a could-not-evaluate, not a "
        "pass."
    ),
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_ROOT = REPO_ROOT / "client"

CSS_FILES = [
    "dist/app.css",
    "css/styles.css",
    "css/modal-titlerow.css",
    "css/confirm-modal.css",
    "dist/app.css",
]

JS_FILES = [
    "js/modal-stack.js",
    "js/app.js",
]

CALLERS = [
    pytest.param(
        "logout", "logout", "confirm", "cancel", "modal-btn-danger",
        id="app.logout",
    ),
    pytest.param(
        "close_session", "close session", "close", "cancel",
        "modal-btn-danger", id="session_row_actions_confirm.close",
    ),
    pytest.param(
        "remove_session", "remove session", "remove", "cancel",
        "modal-btn-danger", id="session_row_actions_confirm.remove",
    ),
    pytest.param(
        "remove_project", "sidebar.project.remove.title",
        "sidebar.project.remove.confirm", "sidebar.group.remove.cancel",
        "modal-btn-danger", id="session_sidebar_heading_actions.removeProject",
    ),
    pytest.param(
        "close_browser", "browser.close.confirm", "browser.menu.close",
        "cancel", "modal-btn-danger",
        id="session_sidebar_browsers.close",
    ),
    pytest.param(
        "remove_group", "sidebar.group.remove.title",
        "sidebar.group.remove.confirm", "sidebar.group.remove.cancel",
        "modal-btn-danger", id="session_sidebar_group_actions.deleteGroup",
    ),
    pytest.param(
        "remove_layout", "layout.remove.title", "layout.remove.confirm",
        "cancel", "modal-btn-danger",
        id="session_sidebar_layouts.remove",
    ),
    pytest.param(
        "discard_unsaved", "discard unsaved changes?", "discard",
        "keep editing", "modal-btn-danger",
        id="config_editor_modal.confirmDiscardIfDirty",
    ),
    pytest.param(
        "reveal_sensitive", "show credentials on screen?", "reveal",
        "keep hidden", "modal-btn-primary",
        id="config_editor_modal.revealSensitive",
    ),
    pytest.param(
        "save_executable", "save executable file?", "save", "cancel",
        "modal-btn-primary", id="config_editor_modal.save_executable",
    ),
    pytest.param(
        "save_credentials", "save credentials file?", "save", "cancel",
        "modal-btn-primary", id="config_editor_modal.save_credentials",
    ),
    pytest.param(
        "remove_model", "remove model", "remove", "cancel",
        "modal-btn-danger", id="providers.removeModel",
    ),
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
<!-- app.js registers a `window.addEventListener('load', () => App.init()...)`
     bootstrap that expects a full authenticated index.html (Auth, Router,
     #auth-screen, etc). This harness only needs `window.App.showConfirmModal`,
     which `new AppController()` already exposes the instant the script
     executes, so the 'load' bootstrap is swallowed before app.js loads
     rather than faking out its many page dependencies. -->
<script>
(function () {
  var realAdd = window.addEventListener.bind(window);
  window.addEventListener = function (type, listener, opts) {
    if (type === 'load') return;
    return realAdd(type, listener, opts);
  };
})();
</script>
__JS__
<script>
// A stub catalog accessor: returns the key itself, exactly as the real
// i18n runtime renders an unresolved key (client/js/i18n/runtime.js) - a
// loud, honest placeholder rather than a second, invented translation
// table. Good enough to probe the confirm-modal chassis, which does not
// care what the strings SAY.
function tr(key) { return key; }

// One entry per real showConfirmModal call site, replicated verbatim
// (title, labels, primaryVariant) from the current source. See the table
// at the top of this file for the file/function each id corresponds to.
var CALLERS = {
    logout: function () {
        return window.App.showConfirmModal(
            'logout',
            'are you sure you want to logout?',
            'any active session will be destroyed.',
            undefined,
            undefined,
            'danger'
        );
    },
    close_session: function () {
        return window.App.showConfirmModal(
            'close session',
            'close "api-work"?',
            'this cannot be undone.',
            'close',
            'cancel',
            'danger'
        );
    },
    remove_session: function () {
        return window.App.showConfirmModal(
            'remove session',
            'remove "api-work"?',
            'this cannot be undone.',
            'remove',
            'cancel',
            'danger'
        );
    },
    remove_project: function () {
        return window.App.showConfirmModal(
            tr('sidebar.project.remove.title'),
            tr('sidebar.project.remove.message'),
            tr('sidebar.project.remove.detail'),
            tr('sidebar.project.remove.confirm'),
            tr('sidebar.group.remove.cancel'),
            'danger'
        );
    },
    close_browser: function () {
        return window.App.showConfirmModal(
            tr('browser.close.confirm'),
            'some-browser',
            tr('browser.close.detail'),
            tr('browser.menu.close'),
            undefined,
            'danger'
        );
    },
    remove_group: function () {
        return window.App.showConfirmModal(
            tr('sidebar.group.remove.title'),
            tr('sidebar.group.remove.message'),
            tr('sidebar.group.remove.detail'),
            tr('sidebar.group.remove.confirm'),
            tr('sidebar.group.remove.cancel'),
            'danger'
        );
    },
    remove_layout: function () {
        return window.App.showConfirmModal(
            tr('layout.remove.title'),
            tr('layout.remove.message'),
            tr('layout.remove.detail'),
            tr('layout.remove.confirm'),
            undefined,
            'danger'
        );
    },
    discard_unsaved: function () {
        return window.App.showConfirmModal(
            'discard unsaved changes?',
            '"config.json" has unsaved edits.',
            'closing now will lose them. this cannot be undone.',
            'discard',
            'keep editing',
            'danger'
        );
    },
    reveal_sensitive: function () {
        return window.App.showConfirmModal(
            'show credentials on screen?',
            '".env" contains credentials, a secret, or a private key.',
            'its contents will be displayed on screen.',
            'reveal',
            'keep hidden'
        );
    },
    save_executable: function () {
        return window.App.showConfirmModal(
            'save executable file?',
            '"hook.py" is code claude code runs automatically.',
            'a backup of the current version is made before saving.',
            'save',
            'cancel'
        );
    },
    save_credentials: function () {
        return window.App.showConfirmModal(
            'save credentials file?',
            '".env" contains credentials, a secret, or a private key.',
            'a backup of the current version is made before saving.',
            'save',
            'cancel'
        );
    },
    remove_model: function () {
        return window.App.showConfirmModal(
            'remove model',
            'remove "gpt-5" from the provider list?',
            null,
            'remove',
            'cancel',
            'danger'
        );
    },
};

window.__open = function (id) {
    window.__result = 'pending';
    CALLERS[id]().then(function (r) { window.__result = r; });
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
                "any confirm dialog renders was measured. Not a pass."
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
        assert pg.evaluate("!!window.App && !!window.App.showConfirmModal"), (
            "app.js did not load, or showConfirmModal is missing"
        )
        assert not errors, f"the page threw while loading: {errors}"
        try:
            yield pg
        finally:
            context.close()
            browser.close()


def _open(page, caller_id: str) -> None:
    page.evaluate("id => window.__open(id)", caller_id)
    page.wait_for_selector(".confirm-modal .modal-titlerow", state="visible")


def _close(page) -> None:
    if page.evaluate("!!document.querySelector('.modal-overlay')"):
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('.modal-overlay')")


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


@pytest.mark.parametrize("caller_id, verb, primary_label, secondary_label, confirm_class", CALLERS)
def test_title_strip_replaces_the_plain_header(
    page, caller_id, verb, primary_label, secondary_label, confirm_class
):
    _open(page, caller_id)
    measured = page.evaluate(
        """() => ({
            headExists: !!document.querySelector('.confirm-modal .modal-titlerow'),
            verbText: (document.querySelector('.confirm-modal__verb') || {})
                .textContent,
            oldHeaderGone: !document.querySelector('.modal-header'),
            overlayHasClass: document.querySelector('.modal-overlay')
                .classList.contains('confirm-modal'),
        })"""
    )
    assert measured["headExists"], measured
    assert measured["oldHeaderGone"], measured
    assert measured["overlayHasClass"], measured
    assert measured["verbText"].strip() == verb, measured
    _close(page)


@pytest.mark.parametrize("caller_id, verb, primary_label, secondary_label, confirm_class", CALLERS)
def test_verb_is_orange_and_uppercase(
    page, caller_id, verb, primary_label, secondary_label, confirm_class
):
    _open(page, caller_id)
    measured = page.evaluate(
        """() => {
            const cs = getComputedStyle(document.querySelector('.confirm-modal__verb'));
            return {color: cs.color, transform: cs.textTransform};
        }"""
    )
    assert measured["color"] == _token(page, "--oc-orange"), measured
    assert measured["transform"] == "uppercase", measured
    _close(page)


@pytest.mark.parametrize("caller_id, verb, primary_label, secondary_label, confirm_class", CALLERS)
def test_confirm_button_wears_the_correct_variant(
    page, caller_id, verb, primary_label, secondary_label, confirm_class
):
    _open(page, caller_id)
    page.wait_for_function("document.activeElement && document.activeElement.id === 'modal-confirm'")
    page.evaluate("() => document.activeElement.blur()")
    settle_transitions(page, "#modal-confirm", 10_000)
    other_class = "modal-btn-primary" if confirm_class == "modal-btn-danger" else "modal-btn-danger"
    expected_border_token = "--oc-coral" if confirm_class == "modal-btn-danger" else "--oc-orange"
    m = page.evaluate(
        """() => {
            const btn = document.querySelector('#modal-confirm');
            return {
                classes: Array.from(btn.classList),
                label: btn.textContent.trim(),
                border: getComputedStyle(btn).borderTopColor,
                borderWidth: getComputedStyle(btn).borderTopWidth,
            };
        }"""
    )
    assert confirm_class in m["classes"], m
    assert other_class not in m["classes"], m
    assert m["label"] == primary_label, m
    assert m["border"] == _token(page, expected_border_token), m
    assert m["borderWidth"] == "1px", m
    _close(page)


@pytest.mark.parametrize("caller_id, verb, primary_label, secondary_label, confirm_class", CALLERS)
def test_cancel_button_stays_secondary(
    page, caller_id, verb, primary_label, secondary_label, confirm_class
):
    _open(page, caller_id)
    m = page.evaluate(
        """() => ({
            classes: Array.from(document.querySelector('#modal-cancel').classList),
            label: document.querySelector('#modal-cancel').textContent.trim(),
        })"""
    )
    assert "modal-btn-secondary" in m["classes"], m
    assert "modal-btn-danger" not in m["classes"], m
    assert m["label"] == secondary_label, m
    _close(page)


@pytest.mark.parametrize("caller_id, verb, primary_label, secondary_label, confirm_class", CALLERS)
def test_both_buttons_show_their_own_edge_brightened_on_focus(
    page, caller_id, verb, primary_label, secondary_label, confirm_class
):
    _open(page, caller_id)
    page.wait_for_function("document.activeElement && document.activeElement.id === 'modal-confirm'")
    for sel in ("#modal-cancel", "#modal-confirm"):
        assert_focus_edge(measure_focus_edge(page, sel), sel)
    _close(page)


@pytest.mark.parametrize("caller_id, verb, primary_label, secondary_label, confirm_class", CALLERS)
def test_cancel_and_confirm_still_resolve_correctly(
    page, caller_id, verb, primary_label, secondary_label, confirm_class
):
    _open(page, caller_id)
    page.click("#modal-cancel")
    page.wait_for_function("window.__result !== 'pending'")
    assert page.evaluate("window.__result") is False
    assert page.evaluate("!document.querySelector('.modal-overlay')")

    _open(page, caller_id)
    page.click("#modal-confirm")
    page.wait_for_function("window.__result !== 'pending'")
    assert page.evaluate("window.__result") is True

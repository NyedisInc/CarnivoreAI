
from __future__ import annotations

import http.server
import json
import socket
import socketserver
import threading
from pathlib import Path

import pytest

pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so NOTHING about how the restart "
        "picker renders was measured. This is a could-not-evaluate, not a "
        "pass."
    ),
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_ROOT = REPO_ROOT / "client"

PHONE = {"width": 390, "height": 844}

MIN_TAP_PX = 44

CSS_FILES = [
    "dist/app.css",
    "css/styles.css",
    "css/modal-titlerow.css",
    "css/session-restart-picker.css",
    "dist/app.css",
]

JS_FILES = [
    "js/session-status-ui.js",
    "js/session-restart-live.js",
    "js/session-restart-options.js",
    "js/modal-stack.js",
    "js/session-restart-picker.js",
]

BUNDLE = "dist/app.js"


SHELL_SENTENCE = (
    "this pane was opened as a plain shell; restarting opens one again"
)
CHROME_SENTENCE = (
    "this pane was opened as a plain shell; claude-chrome is what you picked "
    "and will be started in it instead"
)
CLDL_SENTENCE = "the 'cldl' agent needs a model and none was given"

PREVIEW_SHELL = {
    "name": "row-dead",
    "current_agent_type": None,
    "pane_state": "dead",
    "unchanged": {
        "kind": "shell",
        "detail": SHELL_SENTENCE,
        "command": None,
        "actionable": True,
    },
    "projected": {
        "kind": "shell",
        "detail": SHELL_SENTENCE,
        "command": None,
        "actionable": True,
    },
    "options": [
        {
            "agent_type": "claude-chrome",
            "label": "claude-chrome",
            "is_current": False,
            "resolvable": True,
            "actionable_now": True,
            "kind": "agent",
            "detail": CHROME_SENTENCE,
            "projected_kind": "agent",
            "projected_detail": CHROME_SENTENCE,
            "command": "run-cc",
        },
        {
            "agent_type": "cldl",
            "label": "cldl",
            "is_current": False,
            "resolvable": False,
            "actionable_now": False,
            "kind": "cannot_determine",
            "detail": CLDL_SENTENCE,
            "projected_kind": "cannot_determine",
            "projected_detail": CLDL_SENTENCE,
            "command": None,
        },
    ],
    "wrappers_status": "ok",
}

LIVE_SENTENCE = "this session is still running; there is nothing to restart"

PREVIEW_LIVE = {
    "name": "row-live",
    "current_agent_type": "claude-chrome",
    "pane_state": "alive",
    "unchanged": {
        "kind": "not_dead",
        "detail": LIVE_SENTENCE,
        "command": None,
        "actionable": False,
    },
    "projected": {
        "kind": "shell",
        "detail": SHELL_SENTENCE,
        "command": None,
        "actionable": True,
    },
    "options": [
        {
            "agent_type": "claude-chrome",
            "label": "claude-chrome",
            "is_current": True,
            "resolvable": True,
            "actionable_now": False,
            "kind": "not_dead",
            "detail": LIVE_SENTENCE,
            "projected_kind": "agent",
            "projected_detail": CHROME_SENTENCE,
            "command": "run-cc",
        }
    ],
    "wrappers_status": "ok",
}

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
    --radius-sm: 3px; --radius-md: 6px;
  }
  html, body { margin: 0; background: var(--color-bg); color: var(--color-fg); }
</style>
</head>
<body>
__JS__
<script>
window.__calls = [];
window.__preview = null;
window.API = {
  restartPreview: function (name) {
    window.__calls.push(['restartPreview', name]);
    if (window.__preview === 'reject') {
      return Promise.reject(new Error('the preview route is unreachable'));
    }
    return Promise.resolve(window.__preview);
  },
};
window.__confirms = [];
window.__confirmAnswer = true;
window.App = {
  // The app's ONE confirmation implementation, stubbed and recorded, so
  // a test can assert the live restart NEVER asks it (issue #441).
  showConfirmModal: function (title, message, details, primary, secondary) {
    window.__confirms.push({
      title: title, message: message, details: details,
      primary: primary, secondary: secondary,
    });
    return Promise.resolve(window.__confirmAnswer);
  },
};
window.__open = function (preview, status) {
  window.__preview = preview;
  window.__result = 'pending';
  window.__confirms = [];
  window.SessionRestartPicker.open('row-dead', 'the session', status || null)
    .then(function (r) { window.__result = r; });
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
    js += f'\n<script type="module" src="/static/{BUNDLE}"></script>'
    return HARNESS_HTML.replace("__CSS__", css).replace("__JS__", js)


@pytest.fixture(scope="module")
def base_url() -> str:
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
                f"chromium could not launch ({exc}), so NOTHING about how the "
                "restart picker renders was measured. Not a pass."
            )
        context = browser.new_context(
            viewport=PHONE, is_mobile=True, has_touch=True,
            device_scale_factor=1,
        )
        pg = context.new_page()
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base_url, wait_until="load")
        assert pg.evaluate("document.hidden") is False, (
            "the page reports document.hidden; a backgrounded tab freezes its "
            "render loop and every measurement below would be manufactured"
        )
        assert pg.evaluate("!!window.SessionRestartPicker"), (
            "session-restart-picker.js did not load"
        )
        assert not errors, f"the page threw while loading: {errors}"
        try:
            yield pg
        finally:
            context.close()
            browser.close()


def _open(page, preview, status=None) -> None:
    page.evaluate(
        "args => window.__open(args[0], args[1])", [preview, status]
    )
    page.wait_for_selector(".restart-picker__choice [data-choice-trigger]", state="visible")
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('.restart-picker__content')).transform === 'none'"
    )


OPTIONS_JS = """async () => {
    const trigger = document.querySelector('.restart-picker__choice [data-choice="launch-profile"] [data-choice-trigger]');
    // A TIMER, never a frame: a hidden tab never paints one.
    if (trigger.getAttribute('aria-expanded') !== 'true') { trigger.click(); await new Promise(r => setTimeout(r, 30)); }
    return Array.from(document.querySelectorAll('.restart-picker__choice [data-choice-option]')).map(el => {
        const row = el.querySelector('.lpd');
        const kind = el.querySelector('.lpd-tag--kind');
        const hint = el.querySelector('.cdd__sr[id$="-hint"]');
        const r = el.getBoundingClientRect();
        return {
            value: el.getAttribute('data-choice-option'),
            disabled: el.getAttribute('aria-disabled') === 'true',
            kind: row ? row.getAttribute('data-kind') : null,
            badge: kind ? kind.textContent.trim() : '',
            badgeKind: kind ? kind.getAttribute('data-kind') : '',
            badgeColor: kind ? getComputedStyle(kind).color : '',
            labelColor: row ? getComputedStyle(row.querySelector('.lpd-label')).color : '',
            tags: Array.from(el.querySelectorAll('.lpd-tag')).map(t => t.textContent.trim()),
            detail: hint ? hint.textContent.trim() : '',
            top: r.top, height: r.height, width: r.width, left: r.left,
            opacity: getComputedStyle(el).opacity,
        };
    });
}"""


def _options(page) -> list[dict]:
    return page.evaluate(OPTIONS_JS)


def _arm(page) -> None:
    page.evaluate("() => document.getElementById('restart-picker-live').click()")


def test_the_shell_warning_is_visible_and_not_coloured_like_the_agent(page):
    _open(page, PREVIEW_SHELL)
    _options(page)
    measured = page.evaluate(
        """() => {
            const rows = Array.from(document.querySelectorAll(
                '.restart-picker__choice .lpd-tag--kind'));
            return rows.map(el => {
                const r = el.getBoundingClientRect();
                return {
                    kind: el.getAttribute('data-kind'),
                    text: el.textContent.trim(),
                    color: getComputedStyle(el).color,
                    w: r.width,
                    h: r.height,
                };
            });
        }"""
    )
    measured = [m for m in measured if m["w"] > 0]
    by_kind = {m["kind"]: m for m in measured}
    assert "shell" in by_kind, f"no shell tag was painted: {measured}"
    assert "agent" not in by_kind, f"an agent row is still tagged: {measured}"
    agent_color = page.evaluate(
        """() => getComputedStyle(document.querySelector(
            '[data-choice-option] .lpd[data-kind="agent"] .lpd-label')).color"""
    )
    shell = by_kind["shell"]
    assert shell["w"] > 0 and shell["h"] > 0, "the shell tag has no box"
    assert "plain shell" in shell["text"], (
        f"the shell rung does not say what it is: {shell['text']!r}"
    )
    assert shell["color"] != agent_color, (
        "the shell warning is painted the same colour as the agent option, so "
        f"the stylesheet did not apply: {shell['color']}"
    )
    assert shell["color"] != by_kind["cannot_determine"]["color"], (
        "a plain shell and an unknown outcome are painted alike"
    )
    assert by_kind["cannot_determine"]["color"] != agent_color, (
        "cannot-determine is painted like an agent, which renders an unknown "
        "as a yes"
    )


def test_the_shell_baseline_leads_and_the_current_wrapper_is_marked(page):
    _open(page, PREVIEW_LIVE)
    tops = [
        {"top": o["top"], "value": o["value"], "current": "current" in o["tags"]}
        for o in _options(page)
    ]
    assert len(tops) >= 2, f"the panel is too short to check: {tops}"
    assert tops[0]["value"] == "", "the baseline option is not first"
    assert tops[0]["top"] < tops[1]["top"], (
        "the options are not laid out top to bottom on screen"
    )
    assert tops[1]["current"] is True, (
        "the wrapper the session already records is not marked as current"
    )


def test_a_not_dead_preview_cannot_be_confirmed_at_all(page):
    _open(page, PREVIEW_LIVE)
    assert page.evaluate(
        "document.getElementById('restart-picker-go').disabled"
    ) is True, "the restart button is live over a session that is still running"
    arm = page.evaluate(
        """() => {
            const box = document.getElementById('restart-picker-live');
            const r = box.closest('label').getBoundingClientRect();
            const hint = document.getElementById(
                box.getAttribute('aria-describedby'));
            return {w: r.width, h: r.height, hint: hint.textContent,
                    footer: !!box.closest('.restart-picker__foot')};
        }"""
    )
    assert arm["w"] > 0 and arm["h"] > 0, f"the arm box is not painted: {arm}"
    assert arm["footer"], "the arm box is not next to the action"
    assert "running" in arm["hint"], f"the panel does not say why: {arm}"
    page.evaluate(
        "() => document.getElementById('restart-picker-go').click()"
    )
    assert page.evaluate("window.__result") == "pending", (
        "clicking a disabled restart button still resolved the picker"
    )


def test_a_live_session_is_told_what_it_would_come_back_as(page):
    _open(page, PREVIEW_LIVE)
    seen = _options(page)
    assert seen, "no options were painted for a live session"
    assert all(o["disabled"] for o in seen), (
        f"a live session offered a pickable restart option: {seen}"
    )
    chrome = [o for o in seen if o["value"] == "claude-chrome"]
    assert chrome, f"the configured wrapper was dropped from the list: {seen}"
    assert chrome[0]["kind"] == "agent", (
        "a live session's option does not carry what it would come back as; "
        f"got {chrome[0]}"
    )
    assert chrome[0]["badge"] == "", f"an agent row is tagged: {chrome[0]}"
    assert chrome[0]["detail"], f"the row lost its description: {chrome[0]}"
    baseline = [o for o in seen if o["value"] == ""]
    assert baseline[0]["badgeKind"] == "shell", (
        "the baseline projection for a live session is not shown, so the "
        f"shell landmine is invisible on exactly the rows that carry it: {seen}"
    )
    state = page.evaluate(
        """() => (document.querySelector(
            '.restart-picker__state[data-state="alive"]') || {}).textContent"""
    )
    assert state == "running", (
        f"the header never marks the session as running: {state!r}"
    )


def test_picking_a_wrapper_returns_that_wrapper_and_nothing_else(page):
    _open(page, PREVIEW_SHELL)
    _options(page)
    page.evaluate(
        """() => document.querySelector(
            '[data-choice-option="claude-chrome"]').click()"""
    )
    page.wait_for_function(
        """() => document.querySelector('.restart-picker__choice [data-choice-trigger]')
            .textContent.includes('claude-chrome')"""
    )
    assert page.evaluate(
        "document.getElementById('restart-picker-go').disabled"
    ) is False, "a valid choice left the restart button disabled"
    page.evaluate("() => document.getElementById('restart-picker-go').click()")
    page.wait_for_function("window.__result !== 'pending'")
    assert page.evaluate("window.__result") == {
        "agentType": "claude-chrome",
        "confirmRestartLive": False,
        "mode": "restart",
        "sessionUuid": None,
        "account": None,
    }
    assert page.evaluate("window.__confirms.length") == 0, (
        "a dead pane's restart asked the user to confirm killing something"
    )
    assert page.evaluate("document.querySelector('.restart-picker')") is None, (
        "the panel did not close after the user committed"
    )


def test_an_unavailable_wrapper_is_shown_but_cannot_be_chosen(page):
    _open(page, PREVIEW_SHELL)
    _options(page)
    shown = page.evaluate(
        """() => {
            const row = document.querySelector('[data-choice-option="cldl"]');
            if (!row) return null;
            const r = row.getBoundingClientRect();
            const hit = document.elementFromPoint(
                r.left + r.width / 2, r.top + r.height / 2);
            row.click();
            return {
                disabled: row.getAttribute('aria-disabled') === 'true',
                w: r.width,
                h: r.height,
                opacity: getComputedStyle(row).opacity,
                inPanel: !!(hit && hit.closest('[data-choice-option]')),
                picked: document.querySelector('.restart-picker__choice [data-choice-trigger]')
                    .textContent.includes('cldl'),
            };
        }"""
    )
    assert shown is not None, "the unlaunchable wrapper was dropped from the list"
    assert shown["disabled"] is True, "an unlaunchable wrapper is not marked refused"
    assert shown["picked"] is False, "a click chose an unlaunchable wrapper"
    assert shown["w"] > 0 and shown["h"] > 0, "it is in the DOM but has no box"
    assert float(shown["opacity"]) < 1.0, (
        "an unavailable option is painted exactly like an available one"
    )
    assert shown["inPanel"] is True, "the row is not where it appears to be"


def test_the_panel_fits_a_phone_and_its_rows_clear_a_thumb(page):
    _open(page, PREVIEW_SHELL)
    options = _options(page)
    box = page.evaluate(
        """() => {
            const c = document.querySelector('.restart-picker__content');
            const r = c.getBoundingClientRect();
            const trigger = document.querySelector('.restart-picker__choice [data-choice-trigger]')
                .getBoundingClientRect();
            const panel = document.querySelector('.cdd__panel').getBoundingClientRect();
            return {left: r.left, right: r.right, vw: window.innerWidth,
                    trigger: trigger.height, panelLeft: panel.left, panelRight: panel.right};
        }"""
    )
    box["rows"] = [o["height"] for o in options]
    assert box["trigger"] >= MIN_TAP_PX, f"the dropdown field is under a thumb: {box}"
    assert box["panelLeft"] >= -0.5 and box["panelRight"] <= box["vw"] + 0.5, (
        f"the open list hangs off the screen: {box}"
    )
    assert box["left"] >= -0.5, f"the panel hangs off the left edge: {box}"
    assert box["right"] <= box["vw"] + 0.5, (
        f"the panel hangs off the right edge: {box}"
    )
    assert box["rows"], "no option rows were painted"
    assert min(box["rows"]) >= MIN_TAP_PX, (
        f"an option row is under {MIN_TAP_PX}px tall: {box['rows']}"
    )


def test_a_preview_that_fails_shows_no_panel_and_reports_why(page):
    page.evaluate("() => window.__open('reject', null)")
    page.wait_for_function("window.__result !== 'pending'")
    assert page.evaluate("window.__result") is None
    assert page.evaluate("document.querySelector('.restart-picker')") is None, (
        "a panel was painted even though there was nothing to predict"
    )
    assert "unreachable" in page.evaluate(
        "window.SessionRestartPicker.lastError()"
    ), "a failed preview is indistinguishable from a cancel"


def test_a_busy_row_is_reported_and_never_blocks(page):
    _open(page, PREVIEW_SHELL, status="working")
    state = page.evaluate(
        """() => (document.querySelector(
            '.restart-picker__state[data-state="busy"]') || {}).textContent"""
    )
    assert state == "working", f"a busy row is not mentioned at all: {state!r}"
    assert page.evaluate(
        "document.getElementById('restart-picker-go').disabled"
    ) is False, "a busy row blocked the restart instead of informing about it"


def test_the_wrapper_list_being_unreadable_is_not_an_empty_list(page):
    unreadable = json.loads(json.dumps(PREVIEW_SHELL))
    unreadable["options"] = []
    unreadable["wrappers_status"] = "unavailable"
    _open(page, unreadable)
    text = page.evaluate(
        """() => Array.from(document.querySelectorAll('.restart-picker__notice'))
            .map(el => el.textContent).join(' ')"""
    )
    assert "launch profile list unreadable" in text, (
        f"an unreadable wrapper list rendered as having none: {text!r}"
    )




def test_a_live_session_paints_an_unticked_arm_box_and_no_pickable_option(page):
    _open(page, PREVIEW_LIVE)
    arm = page.evaluate(
        """() => {
            const el = document.getElementById('restart-picker-live');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {checked: el.checked, w: r.width, h: r.height};
        }"""
    )
    assert arm is not None, "a live session was given no way to restart at all"
    assert arm["checked"] is False, "the panel opened already armed to kill"
    assert arm["w"] > 0 and arm["h"] > 0, "the arm control has no box on screen"

    locked = [o["disabled"] for o in _options(page)]
    assert locked and all(locked), (
        f"a live session offered a pickable option before arming: {locked}"
    )
    assert page.evaluate(
        "document.getElementById('restart-picker-go').disabled"
    ) is True, "the restart button was live before anything was armed"


def test_ticking_the_arm_box_unlocks_the_choices_and_renames_the_button(page):
    _open(page, PREVIEW_LIVE)
    page.evaluate(
        "() => document.getElementById('restart-picker-live').click()"
    )
    unlocked = [o["disabled"] for o in _options(page)]
    assert not any(unlocked), (
        f"arming the panel did not unlock the choices: {unlocked}"
    )
    assert page.evaluate(
        "document.getElementById('restart-picker-go').textContent.trim()"
    ) == "kill and restart", (
        "the button still says 'restart' for an operation that kills a "
        "running process"
    )
    page.evaluate("() => document.getElementById('restart-picker-live').click()")
    relocked = [o["disabled"] for o in _options(page)]
    assert all(relocked), f"unticking the box left the choices open: {relocked}"


def test_an_armed_live_restart_fires_at_once_with_no_confirm_modal(page):
    _open(page, PREVIEW_LIVE)
    page.evaluate("() => { window.__confirmAnswer = false; }")
    page.evaluate("() => document.getElementById('restart-picker-live').click()")
    page.evaluate("() => document.getElementById('restart-picker-go').click()")
    page.wait_for_function("window.__result !== 'pending'")

    assert page.evaluate("window.__confirms") == [], (
        "a confirm modal was shown after the armed click"
    )
    assert page.evaluate("document.querySelector('.restart-picker')") is None, (
        "the picker stayed open after the armed click"
    )
    page.evaluate("() => { window.__confirmAnswer = true; }")

    assert page.evaluate("window.__result") == {
        "agentType": None,
        "confirmRestartLive": True,
        "mode": "restart",
        "sessionUuid": None,
        "account": None,
    }



REMOVED_PROSE = [
    "this stops what is in the pane",
    "the transcript is kept",
    "so the choices below are locked",
    "would start the agent",
    "kill what is running and restart this session in place",
    "this kills what is running in the pane first",
    "leave it on",
]


@pytest.mark.parametrize("width", [390, 1440])
def test_the_prose_is_gone_and_the_choices_fit(page, width):
    page.set_viewport_size({"width": width, "height": 844})
    _open(page, PREVIEW_LIVE)
    seen = page.evaluate(
        """() => {
            const root = document.querySelector('.restart-picker__content');
            const out = [];
            const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            while (walk.nextNode()) {
                const n = walk.currentNode;
                const r = n.parentElement.getBoundingClientRect();
                if (r.width > 1 && r.height > 1) out.push(n.textContent);
            }
            return out.join(' ');
        }"""
    )
    for gone in REMOVED_PROSE:
        assert gone not in seen, f"{gone!r} is still on screen at {width}px"
    assert "restart" in seen and "the session" in seen, seen
    fit = page.evaluate(
        """() => {
            const l = document.querySelector('.restart-picker__choice');
            const d = document.querySelector('.restart-picker__content')
                .getBoundingClientRect();
            return {sh: l.scrollHeight, ch: l.clientHeight,
                    right: d.right, bottom: d.bottom,
                    vw: innerWidth, vh: innerHeight};
        }"""
    )
    assert fit["sh"] <= fit["ch"] + 1, f"the common list scrolls: {fit}"
    assert fit["right"] <= fit["vw"] and fit["bottom"] <= fit["vh"], (
        f"the panel does not fit the viewport: {fit}"
    )


def test_arrows_move_enter_chooses_escape_closes_the_list_then_the_dialog(page):
    _open(page, PREVIEW_SHELL)
    assert page.evaluate("document.activeElement.hasAttribute('data-choice-trigger')"), (
        "the dropdown did not take focus"
    )
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_function(
        """() => document.querySelector('.restart-picker__choice [data-choice-trigger]')
            .textContent.includes('claude-chrome')"""
    )
    assert page.evaluate("window.__result") == "pending", (
        "enter on the dropdown confirmed the dialog instead of choosing"
    )
    page.evaluate("() => document.getElementById('restart-picker-go').click()")
    page.wait_for_function("window.__result !== 'pending'")
    result = page.evaluate("window.__result")
    assert result and result["agentType"] == "claude-chrome", result
    assert result["confirmRestartLive"] is False, result

    _open(page, PREVIEW_SHELL)
    page.keyboard.press("ArrowDown")
    assert page.evaluate("!!document.querySelector('[data-choice-list]')"), "the list did not open"
    page.keyboard.press("Escape")
    assert page.evaluate("!!document.querySelector('.restart-picker')"), (
        "escape with the list open closed the whole dialog"
    )
    assert page.evaluate("!document.querySelector('[data-choice-list]')"), "escape left the list open"
    page.keyboard.press("Escape")
    page.wait_for_function("window.__result !== 'pending'")
    assert page.evaluate("window.__result") is None, "escape did not cancel"
    assert page.evaluate("!document.querySelector('.restart-picker')"), (
        "escape left the panel on screen"
    )


def test_a_locked_live_panel_focuses_the_arm_box_and_enter_does_nothing(page):
    _open(page, PREVIEW_LIVE)
    assert page.evaluate("document.activeElement.id") == "restart-picker-live"
    page.keyboard.press("Enter")
    assert page.evaluate("window.__result") == "pending", (
        "enter on an unticked arm box resolved the picker"
    )

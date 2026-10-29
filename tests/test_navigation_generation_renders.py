
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_nav_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_nav_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so NOTHING about what this page renders "
        "was measured. This is a could-not-evaluate, not a pass."
    ),
)

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

VIEWPORT = {"width": 900, "height": 700}

HARNESS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  .screen { display: none; }
  .screen.active { display: block; }
  #header-title-text { font: 16px monospace; }
</style>
</head>
<body>
  <div id="auth-screen" class="screen"></div>
  <div id="launchpad-screen" class="screen"></div>
  <div id="terminal-screen" class="screen">
    <span id="header-title-text"></span>
  </div>
  <div id="archive-screen" class="screen"></div>

  <script src="/static/js/navigation-generation.js"></script>
  <script src="/static/js/app-screen-entry.js"></script>
  <script src="/static/js/app.js"></script>
  <!-- THE ONE STRING CATALOG, booted the way client/index.html boots it:
       a module, so it runs after the classic scripts and before load.
       app.js reads window.CloudeI18n at render time (the header's rename
       pencil), so a harness without it throws mid-switch and the socket
       is never opened. -->
  <script type="module" src="/static/js/i18n/boot.js"></script>
  <script>
    // app.js registers a window 'load' handler calling App.init(), which wants
    // the whole authenticated app. Neutralise it BEFORE load fires. This is
    // not re-running anything: it stops an init from running a FIRST time in
    // an environment that cannot support it.
    window.App.init = function () {};

    // ---- the network, under the test's control -----------------------
    // Each getSession() hands back a promise the test resolves by hand. The
    // ORDER those resolve in is the entire scenario, and a real fetch could
    // not express it.
    window.__pending = {};
    window.API = {
      getSession: function (id) {
        return new Promise(function (resolve) { window.__pending[id] = resolve; });
      },
      adoptSession: function () { return Promise.resolve({ session: {} }); }
    };
    window.__resolveSession = function (id, payload) {
      var r = window.__pending[id];
      delete window.__pending[id];
      r(payload);
    };

    // ---- the write that cannot be taken back -------------------------
    // Every socket the controller would open is recorded instead. A
    // superseded navigation reaching this list is the bug.
    window.__connects = [];
    window.TerminalController = {
      term: {},
      pauseForHome: function () {},
      reconnectToExistingSession: function (info) {
        window.__connects.push((info.session && info.session.id) || null);
        return Promise.resolve();
      },
      connectToSession: function (s) {
        window.__connects.push(s && s.id);
        return Promise.resolve();
      }
    };

    // ---- collaborators app.js reaches for ----------------------------
    window.ScreenChrome = { apply: function () {} };
    window.ThemeNavigation = { applyForSession: function () {},
                               applyForGlobal: function () {} };
    window.SessionSidebar = { show: function () {}, hide: function () {},
                              setActiveSession: function () {} };
    // NO window.DPad STUB. app.js stopped calling init/show/hide when
    // the d-pad button was replaced by the terminal key bar, and a stub
    // for calls nothing makes is one more thing to keep true.
    window.SlashCommandsModal = { button: {},
        init: function () { return Promise.resolve(); },
        show: function () {}, hide: function () {} };
    window.Launchpad = { loadProjects: function () {}, init: function () {},
                         renderLaunchpadUI: function () {} };
    window.Router = { resetToLauncher: function () {} };

    var app = window.App;
    app.logoutBtn = document.createElement('button');
    app.settingsBtn = document.createElement('button');
    app.configEditorBtn = document.createElement('button');
    app._placeStatusLight = function () {};
    app._syncSessionUrl = function () {};
    app.focusTerminal = function () {};
    app.currentScreen = 'launchpad';

    // ---- the gesture ------------------------------------------------
    // The bundle's activateRow steps (web/src/lib/drawer/row-switch.ts). Returns the promise so the test can await each click.
    window.__ctrl = { _activeTmuxName: null, _closeAfterSwitch: function () {} };
    window.__click = function (name, sessionId) {
      var nav = window.NavigationGeneration.begin('session:' + name);
      return window.API.getSession(sessionId).then(function (info) {
        if (!window.NavigationGeneration.keep(nav, 'sidebar switch to ' + name)) return undefined;
        window.__ctrl._closeAfterSwitch();
        return window.App.returnToExistingTerminal(info);
      });
    };
    // PLAYWRIGHT'S evaluate() AWAITS A RETURNED PROMISE, and an
    // assignment expression evaluates TO the value assigned. So
    // "start a click and do not wait for it" has to hand back
    // undefined, and waiting for one has to be its own call. Getting
    // this wrong hangs the test on the very fetch it is deliberately
    // holding open.
    window.__runs = {};
    window.__start = function (key, name, sessionId) {
      window.__runs[key] = window.__click(name, sessionId);
    };
    window.__settle = function (key) {
      return window.__runs[key].then(function () { return true; });
    };
    window.__ready = true;
  </script>
</body>
</html>
"""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def live_harness():
    import uvicorn

    app = FastAPI()

    @app.get("/")
    def harness() -> HTMLResponse:
        """The harness page."""
        return HTMLResponse(HARNESS_HTML)

    app.mount(
        "/static",
        StaticFiles(directory=str(REPO_ROOT / "client")),
        name="static",
    )

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        pytest.fail("the test server did not start, so nothing was measured")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="function")
def page(live_harness):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(
                f"chromium could not launch ({exc}), so NOTHING about what "
                "this page renders was measured."
            )
        context = browser.new_context(viewport=VIEWPORT)
        pg = context.new_page()
        pg.goto(live_harness)
        pg.wait_for_function("window.__ready === true && !!window.CloudeI18n")

        assert pg.evaluate("document.hidden") is False, (
            "the page reports document.hidden; a backgrounded tab freezes "
            "rendering and makes every measurement here meaningless"
        )
        yield pg
        context.close()
        browser.close()


def _painted_title(page) -> str:
    return page.evaluate(
        "() => (document.getElementById('header-title-text').textContent || '').trim()"
    )


def _active_screen(page) -> str:
    return page.evaluate(
        "() => { const el = document.querySelector('.screen.active');"
        " return el ? el.id : ''; }"
    )


def _info(session_id: str, label: str) -> dict:
    return {
        "session": {"id": session_id, "tmux_session": f"cloude_{label}"},
        "tmux_session": f"cloude_{label}",
        "label": label,
    }


def test_a_switch_resolved_in_order_really_paints(page):
    page.evaluate("__start('A', 'cloude_alpha', 'ses_a')")
    page.evaluate(
        "(p) => window.__resolveSession('ses_a', p)", _info("ses_a", "alpha")
    )
    page.evaluate("__settle('A')")

    assert _painted_title(page) == "alpha"
    assert _active_screen(page) == "terminal-screen"
    assert page.evaluate("window.__connects") == ["ses_a"]


def test_a_late_completion_never_paints_over_the_session_the_user_moved_to(page):
    page.evaluate("__start('A', 'cloude_alpha', 'ses_a')")
    page.evaluate("__start('B', 'cloude_beta', 'ses_b')")

    page.evaluate(
        "(p) => window.__resolveSession('ses_b', p)", _info("ses_b", "beta")
    )
    page.evaluate("__settle('B')")
    assert _painted_title(page) == "beta"

    page.evaluate(
        "(p) => window.__resolveSession('ses_a', p)", _info("ses_a", "alpha")
    )
    page.evaluate("__settle('A')")

    assert _painted_title(page) == "beta", (
        "session A resolved after the user had moved to B and repainted the "
        "header, which is the bug the navigation token exists to make "
        "impossible"
    )
    assert _active_screen(page) == "terminal-screen"
    assert page.evaluate("window.__connects") == ["ses_b"], (
        "and A must not have opened a socket - that is the write that cannot "
        "be taken back, because it streams another conversation's bytes"
    )


def test_the_last_click_wins_even_when_it_answers_first(page):
    page.evaluate("__start('A', 'cloude_alpha', 'ses_a')")
    page.evaluate("__start('B', 'cloude_beta', 'ses_b')")

    page.evaluate(
        "(p) => window.__resolveSession('ses_a', p)", _info("ses_a", "alpha")
    )
    page.evaluate("__settle('A')")
    assert _painted_title(page) == "", (
        "A had already been superseded when it answered, so it must not have "
        "painted anything at all"
    )

    page.evaluate(
        "(p) => window.__resolveSession('ses_b', p)", _info("ses_b", "beta")
    )
    page.evaluate("__settle('B')")

    assert _painted_title(page) == "beta"
    assert page.evaluate("window.__connects") == ["ses_b"]


def test_a_then_b_then_a_again_and_the_first_visit_still_loses(page):
    page.evaluate("__start('A1', 'cloude_alpha', 'ses_a')")
    page.evaluate("__start('B', 'cloude_beta', 'ses_b')")
    page.evaluate(
        "(p) => window.__resolveSession('ses_b', p)", _info("ses_b", "beta")
    )
    page.evaluate("__settle('B')")

    page.evaluate("__start('A2', 'cloude_alpha', 'ses_a2')")
    page.evaluate(
        "(p) => window.__resolveSession('ses_a2', p)", _info("ses_a", "alpha")
    )
    page.evaluate("__settle('A2')")
    assert _painted_title(page) == "alpha"

    page.evaluate(
        "(p) => window.__resolveSession('ses_a', p)",
        _info("ses_a", "alpha-stale"),
    )
    page.evaluate("__settle('A1')")

    assert _painted_title(page) == "alpha", (
        "the first visit to A must not be satisfied by its own late fetch, "
        "even though the user is back in A - the screen was rebuilt in between"
    )
    assert page.evaluate("window.__connects") == ["ses_b", "ses_a"]


def test_going_home_stops_an_in_flight_session_entry_from_painting(page):
    page.evaluate("__start('A', 'cloude_alpha', 'ses_a')")
    page.evaluate("window.App.showLaunchpad()")
    assert _active_screen(page) == "launchpad-screen"

    page.evaluate(
        "(p) => window.__resolveSession('ses_a', p)", _info("ses_a", "alpha")
    )
    page.evaluate("__settle('A')")

    assert _active_screen(page) == "launchpad-screen", (
        "the session resolved after the user went home and swapped the screen "
        "out from under them"
    )
    assert page.evaluate("window.__connects") == []


from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_theme_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_theme_logs_"))
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
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

VIEWPORT = {"width": 900, "height": 700}

PROBE_VAR = "--color-bg"

THEME_COLORS = {
    "claude": "rgb(30, 30, 30)",
    "matrix": "rgb(0, 255, 0)",
    "nord": "rgb(46, 52, 64)",
}


def _manifest(theme_id: str) -> dict:
    return {
        "id": theme_id,
        "name": theme_id,
        "description": f"{theme_id} test manifest",
        "author": "test",
        "version": "1.0.0",
        "source": "builtin",
        "cssVars": {
            PROBE_VAR: THEME_COLORS[theme_id],
            "--color-header-bg": THEME_COLORS[theme_id],
            "--color-bg-page": THEME_COLORS[theme_id],
        },
        "xterm": {"background": THEME_COLORS[theme_id], "foreground": "#ffffff"},
    }


HARNESS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<!-- THE REAL STYLESHEETS, IN THE ORDER client/index.html LOADS THEM. The
     chrome question this file answers - does the top bar follow the home
     page theme - is decided entirely by the real token layer
     (web/src/opscenter/tokens.css, compiled into dist/app.css) and the real
     chrome rules in terminal-carnivore.css. A synthetic stylesheet here
     would answer a question nobody asked. -->
<link rel="stylesheet" href="/static/css/styles.css">
<link rel="stylesheet" href="/static/dist/app.css">
<link rel="stylesheet" href="/static/css/terminal-carnivore.css">
<style>
  /* The pixel under test. The theme registry paints PROBE_VAR onto
     document.documentElement.style; this rule is what turns that into
     something a human can see. */
  body { background-color: var(--color-bg, rgb(255, 0, 255)); margin: 0; }
  #probe { width: 400px; height: 300px; background-color: var(--color-bg, rgb(255, 0, 255)); }
  /* The three regions the owner named, each reading the SAME custom
     property. Two of them are chrome and sit outside #terminal-screen,
     exactly as client/index.html places the header and the conversations
     sidebar; the third is the session's own terminal component. A session
     pin is painted inline on #terminal-container, so the cascade is what
     decides which of these three follows it. */
  #top-bar { width: 400px; height: 40px; background-color: var(--color-bg, rgb(255, 0, 255)); }
  #conversations { width: 400px; height: 40px; background-color: var(--color-bg, rgb(255, 0, 255)); }
  #terminal-probe { width: 400px; height: 40px; background-color: var(--color-bg, rgb(255, 0, 255)); }
  .screen { display: none; }
  .screen.active { display: block; }
  /* The two chrome regions keep the real stylesheets' background and are
     only given a box to measure, so what they paint is the shipped rule. */
  .header, #session-sidebar-panel { display: block; width: 400px; height: 40px; }
</style>
</head>
<body>
  <div id="probe"></div>
  <div id="top-bar"></div>
  <div id="conversations"></div>
  <!-- THE REAL CHROME, with the real class and id the shipped stylesheets
       select on: the top bar with the logo, and the conversations pane. -->
  <div class="header"></div>
  <aside id="session-sidebar-panel" class="session-sidebar-panel"></aside>
  <div id="auth-screen" class="screen"></div>
  <div id="launchpad-screen" class="screen"></div>
  <div id="terminal-screen" class="screen">
    <div id="terminal-container"><div id="terminal-probe"></div></div>
  </div>
  <div id="archive-screen" class="screen"></div>

  <!-- Carnivore rename Phase 7 (docs/rename-carnivore.md): the dual-key
       localStorage read/write helper. registry.js's own STORAGE_KEY is
       'carnivore.theme'; without this module loaded, reading it finds
       nothing when a test (or a real pre-rename browser profile) only
       has the legacy 'cloude.theme' key, and getStoredThemeId() falls
       through to DEFAULT_THEME_ID ('carnivore') instead of the real
       stored choice. A real dependency in index.html (loaded there
       before themes/registry.js too), so it is loaded here too. -->
  <script type="module" src="/static/js/browser-storage-migrate.js"></script>
  <script src="/static/js/themes/registry.js"></script>
  <script src="/static/js/theme-navigation.js"></script>
  <script src="/static/js/app-screen-entry.js"></script>
  <script src="/static/js/app.js"></script>
  <script>
    // app.js registers a window 'load' handler that calls App.init(), which
    // wants the whole authenticated app. Neutralise it BEFORE load fires.
    // This is not "re-running" anything - it stops an init from running a
    // first time in an environment that cannot support it.
    window.App.init = function () {};

    // Collaborator stubs. The theme chain below them is entirely real.
    window.ScreenChrome = { apply: function () {} };
    window.SessionSidebar = { show: function () {}, hide: function () {},
                              setActiveSession: function () {} };
    window.TerminalController = { term: {}, pauseForHome: function () {},
        reconnectToExistingSession: function () { return Promise.resolve(); },
        connectToSession: function () { return Promise.resolve(); } };
    // NO window.DPad STUB. app.js stopped calling init/show/hide when
    // the d-pad button was replaced by the terminal key bar, and a stub
    // for calls nothing makes is one more thing to keep true.
    window.SlashCommandsModal = { button: {},
        init: function () { return Promise.resolve(); },
        show: function () {}, hide: function () {} };
    window.Launchpad = { loadProjects: function () { return Promise.resolve(); },
        render: function () { return Promise.resolve(); },
        init: function () { return Promise.resolve(); },
        show: function () { return Promise.resolve(); },
        renderLaunchpadUI: function () {} };
    window.Router = { resetToLauncher: function () {} };

    var app = window.App;
    app.logoutBtn = document.createElement('button');
    app.settingsBtn = document.createElement('button');
    app.configEditorBtn = document.createElement('button');
    app._placeStatusLight = function () {};
    app._syncSessionUrl = function () {};
    app._consumeStashedArchiveRoute = function () { return false; };
    app.currentScreen = 'launchpad';

    // Themes.init() is called EXACTLY ONCE, here. Tests never call it again.
    //
    // WAITS FOR DOMContentLoaded FIRST, and that wait is load-bearing, not
    // decorative. browser-storage-migrate.js is a `type="module"` script,
    // which the HTML spec always defers: it runs after every classic
    // <script src> in the document but BEFORE DOMContentLoaded (the same
    // ordering client/index.html's own comment relies on). This inline
    // script is itself a plain classic script, so without the listener it
    // would run DURING parsing - before that deferred module has executed -
    // and Themes.init()'s read of the persisted theme id would find
    // window.BrowserStorageMigrate still undefined, silently losing the
    // legacy-key fallback this suite depends on. In real production this
    // race cannot happen: Themes.init() is only ever called from
    // App.init(), which app.js itself gates behind the page's 'load' event
    // (see client/js/app.js's `window.addEventListener('load', ...)`),
    // which fires well after DOMContentLoaded. This listener reproduces
    // that same ordering without pulling in the whole authenticated
    // App.init() this harness deliberately stubs out above.
    document.addEventListener('DOMContentLoaded', () => {
        window.__themesReady = window.Themes.init();
    });
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

    @app.get("/api/v1/themes")
    def themes() -> JSONResponse:
        """The manifest list the real registry fetches on init."""
        return JSONResponse([_manifest(t) for t in THEME_COLORS])

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
        context.add_init_script("try { localStorage.setItem('cloude.theme', 'claude'); } catch (e) {}")
        pg = context.new_page()
        pg.goto(live_harness)
        pg.wait_for_function("window.__themesReady !== undefined")
        pg.evaluate("window.__themesReady")

        assert pg.evaluate("document.hidden") is False, (
            "the page reports document.hidden; a backgrounded tab freezes "
            "rendering, pins transitions at their start value and makes every "
            "measurement here meaningless"
        )
        yield pg
        context.close()
        browser.close()


def _settled_bg(page, selector: str = "#probe") -> str:
    return page.evaluate(
        """(sel) => new Promise((resolve, reject) => {
            const el = document.querySelector(sel);
            if (!el) { reject(new Error('no element for ' + sel)); return; }
            let previous = null;
            let frames = 0;
            const tick = () => {
                const value = getComputedStyle(el).backgroundColor;
                if (value === previous) { resolve(value); return; }
                previous = value;
                if (++frames > 120) { resolve(value); return; }
                requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
        })""",
        selector,
    )


def _chrome_colors(page) -> dict:
    _settled_bg(page, ".header")
    return page.evaluate(
        """() => ({
            header: getComputedStyle(document.querySelector('.header')).backgroundColor,
            conversations: getComputedStyle(
                document.querySelector('#session-sidebar-panel')).backgroundColor,
        })"""
    )


def _enter_session(page, name: str, pin: str | None, session_id: str | None = None):
    page.evaluate(
        """([name, pin, sid]) => {
            const info = {
                tmux_session: name,
                pinned_theme: pin,
                agent_type: null,
                label: name,
                session: { id: sid || name, working_dir: '/tmp', pty_pid: 1 },
            };
            // The async tail reconnects a websocket and is not under test; its
            // rejection is swallowed HERE, in the test, never in shipped code.
            const p = window.App.returnToExistingTerminal(info);
            if (p && p.catch) p.catch(() => {});
        }""",
        [name, pin, session_id],
    )


def test_switching_to_an_unpinned_session_repaints_to_the_global_theme(page):
    assert _settled_bg(page) == THEME_COLORS["claude"], (
        "the harness must start on the user's own global theme"
    )

    _enter_session(page, "cloude_a", "matrix")
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["matrix"], (
        "entering a session with a pinned theme must repaint that session's "
        "own terminal component to the pin"
    )

    _enter_session(page, "cloude_b", None)
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["claude"], (
        "switching from a PINNED session straight into an UNPINNED one must "
        "repaint to the user's own global theme. Before the fix this branch "
        "applied nothing at all, so the pixel stayed "
        f"{THEME_COLORS['matrix']} (matrix green) and this assertion failed."
    )


def test_one_screen_two_themes_the_chrome_never_follows_a_pin(page):
    _enter_session(page, "cloude_argent", "matrix")

    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["matrix"], (
        "the pinned session's own terminal component wears its pin"
    )
    assert _settled_bg(page, "#top-bar") == THEME_COLORS["claude"], (
        "the top bar with the logo stays on the home-page theme"
    )
    assert _settled_bg(page, "#conversations") == THEME_COLORS["claude"], (
        "and so does the conversations pane"
    )
    assert _settled_bg(page, "body") == THEME_COLORS["claude"], (
        "and so does the page itself"
    )
    assert page.evaluate("document.documentElement.dataset.theme") == "claude", (
        "the ROOT attribute is the global theme; a pin never reaches it"
    )

    chrome_pinned = _chrome_colors(page)
    assert chrome_pinned["header"] == THEME_COLORS["claude"], (
        "the real top bar holds the home-page theme, not the session pin"
    )
    assert chrome_pinned["conversations"] == THEME_COLORS["claude"], (
        "and so does the real conversations pane"
    )

    assert page.evaluate(
        "window.Themes.getSessionManifest({pinnedTheme: null}).id"
    ) == "claude", (
        "an unpinned session on the same screen follows the home-page theme"
    )
    assert page.evaluate(
        "window.Themes.getSessionManifest({pinnedTheme: 'nord'}).id"
    ) == "nord", (
        "and a differently pinned one wears its own pin, at the same moment"
    )
    assert page.evaluate("window.Themes.resolveTerminalThemeId()") == "matrix", (
        "positive control: the page's own pane really is in matrix scope, so "
        "the two answers above came from their own inputs and not from a "
        "resolver that had simply stopped reading the page scope"
    )

    page.evaluate("localStorage.setItem('carnivore.theme', 'nord')")
    page.evaluate("window.ThemeNavigation.reapply()")
    chrome_after = _chrome_colors(page)
    assert chrome_after["header"] == THEME_COLORS["nord"], (
        "the real top bar must REPAINT to the new home-page theme; a bar "
        f"still on {chrome_pinned['header']} is a bar bound to a literal"
    )
    assert chrome_after["conversations"] == THEME_COLORS["nord"], (
        "and so must the real conversations pane"
    )
    assert chrome_after["header"] != chrome_pinned["header"], (
        "positive control: the two readings must differ, or this test "
        "proved nothing about the chrome being able to change"
    )
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["matrix"], (
        "AND THE PIN STILL WINS THROUGH ALL OF IT: the chrome moved to the "
        "new global theme and the pinned session's terminal did not move"
    )


def test_the_unpinned_repaint_is_visible_in_an_actual_screenshot(page):
    from PIL import Image
    import io

    def sample() -> tuple:
        box = page.locator("#terminal-probe").bounding_box()
        shot = page.screenshot(clip=box)
        img = Image.open(io.BytesIO(shot)).convert("RGB")
        return img.getpixel((int(box["width"] / 2), int(box["height"] / 2)))

    _enter_session(page, "cloude_a", "matrix")
    _settled_bg(page, "#terminal-probe")
    assert sample() == (0, 255, 0), (
        "the pinned session's theme must be the colour actually painted"
    )

    _enter_session(page, "cloude_b", None)
    _settled_bg(page, "#terminal-probe")
    assert sample() == (30, 30, 30), (
        "the unpinned session must render the global theme. A stale "
        "(0, 255, 0) here is the reported bug, seen in the pixels themselves."
    )


def test_going_home_from_a_session_repaints_to_the_global_theme(page):
    _enter_session(page, "cloude_a", "matrix")
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["matrix"]

    page.evaluate("window.App.showLaunchpad()")
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["claude"]
    assert _settled_bg(page) == THEME_COLORS["claude"]
    assert page.evaluate("window.Themes.getActiveSession()") is None, (
        "the home screen is not a session, so nothing may still hold theme "
        "scope - a picker swap there must write the global default, not PATCH "
        "a pin onto a session the user has left"
    )


def test_a_session_switch_honours_the_users_own_global_choice(page):
    page.evaluate("localStorage.setItem('carnivore.theme', 'nord')")
    _enter_session(page, "cloude_a", "matrix")
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["matrix"]
    assert _settled_bg(page) == THEME_COLORS["nord"], (
        "and the page moved to the user's new global choice on the same "
        "navigation, rather than following the pin"
    )

    _enter_session(page, "cloude_b", None)
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["nord"], (
        "the restore target is whatever the user chose globally"
    )


def test_an_adopted_session_switch_repaints_and_scopes_by_tmux_name(page):
    _enter_session(page, "cloude_a", "matrix")
    _enter_session(page, "legacy_pane", None, "adopted:legacy_pane")

    assert _settled_bg(page) == THEME_COLORS["claude"], (
        "an unpinned ADOPTED session must repaint like any other unpinned one"
    )
    assert page.evaluate("window.Themes.getActiveSession()") == "legacy_pane"


def test_a_pin_naming_an_uninstalled_theme_does_not_leave_the_previous_one(page):
    _enter_session(page, "cloude_a", "matrix")
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["matrix"]

    _enter_session(page, "cloude_b", "a-theme-the-user-uninstalled")
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["claude"], (
        "a pin the registry cannot resolve must fall back to the global theme"
    )


def test_a_reload_while_in_a_session_lands_on_the_same_theme(page, live_harness):
    _enter_session(page, "cloude_a", "matrix")
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["matrix"]

    page.reload()
    page.wait_for_function("window.__themesReady !== undefined")
    page.evaluate("window.__themesReady")
    assert page.evaluate("document.hidden") is False
    assert _settled_bg(page) == THEME_COLORS["claude"], (
        "a reload starts from the user's global theme, not the session pin "
        "that happened to be painted before it"
    )

    _enter_session(page, "cloude_b", None)
    assert _settled_bg(page, "#terminal-probe") == THEME_COLORS["claude"]

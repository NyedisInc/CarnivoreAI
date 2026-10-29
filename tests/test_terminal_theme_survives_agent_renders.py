
from __future__ import annotations

import io
import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_termtheme_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_termtheme_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so NOTHING about what this terminal "
        "renders was measured. This is a could-not-evaluate, not a pass."
    ),
)

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

VIEWPORT = {"width": 1100, "height": 800}

THEME_IDS = ("claude", "dracula", "matrix")

CHANNEL_TOLERANCE = 6


def _manifest(theme_id: str) -> dict:
    path = REPO_ROOT / "client" / "css" / "themes" / theme_id / "theme.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["source"] = "builtin"
    return data


MANIFESTS = {theme_id: _manifest(theme_id) for theme_id in THEME_IDS}
DRACULA = MANIFESTS["dracula"]
CLAUDE = MANIFESTS["claude"]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


HARNESS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="/static/vendor/xterm/xterm.css" />
<style>
  body { margin: 0; background: #808080; }
  .screen { display: none; }
  .screen.active { display: block; }
  /* A fixed box so the terminal has a stable geometry to sample. */
  #terminal { width: 900px; height: 500px; }
</style>
</head>
<body>
  <div id="auth-screen" class="screen"></div>
  <div id="launchpad-screen" class="screen"></div>
  <div id="archive-screen" class="screen"></div>
  <div id="terminal-screen" class="screen">
    <!-- THE SESSION'S OWN COMPONENT. A session-scoped theme is painted
         onto this container, not onto #terminal-screen, which is the
         whole page - see issue #318. -->
    <div id="terminal-container">
      <div id="terminal"></div>
    </div>
  </div>

  <script src="/static/vendor/xterm/xterm.js"></script>
  <script src="/static/vendor/xterm/xterm-addon-fit.js"></script>
  <script src="/static/vendor/xterm/xterm-addon-webgl.js"></script>
  <script src="/static/vendor/xterm/xterm-addon-unicode11.js"></script>
  <script src="/static/js/terminal-background-opacity.js"></script>
  <!-- The two bounded waits terminal.js uses to decide the xterm bundle
       has loaded and the container can be measured. A real dependency in
       index.html, so it is loaded here too: without it this page measures
       terminal.js's degraded fallback rather than the code that runs in
       the browser. -->
  <script src="/static/js/terminal-readiness.js"></script>
  <!-- The terminal client factory. terminal.js's boot line is one call
       into it, so without it this page gets NO window.TerminalController
       at all and measures nothing. A real dependency in index.html, and
       loaded before terminal.js there for the same reason. -->
  <script src="/static/js/terminal-client-factory.js"></script>
  <script src="/static/js/terminal.js"></script>
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
    // This stops an init from running a first time in an environment that
    // cannot support it; nothing here re-runs an init to see whether it ran.
    window.App.init = function () {};

    // The REAL terminal controller, with only its two network entry points
    // replaced. initTerminal() - which builds the xterm instance, attaches
    // the opacity adapter and subscribes to the theme registry - is the
    // shipped one and is what every assertion below measures.
    window.TerminalController.connectToSession = function () { return Promise.resolve(); };
    window.TerminalController.reconnectToExistingSession = function () { return Promise.resolve(); };
    window.TerminalController.pauseForHome = function () {};

    // Collaborator stubs. The theme and terminal chain below them is real.
    window.ScreenChrome = { apply: function () {} };
    window.SessionSidebar = { show: function () {}, hide: function () {},
                              setActiveSession: function () {} };
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
    app.focusTerminal = function () {};
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
        return JSONResponse(list(MANIFESTS.values()))

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
                "this terminal renders was measured."
            )
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        allowlist_json = json.dumps(json.dumps({theme_id: False for theme_id in THEME_IDS}))
        context.add_init_script(
            "try {"
            " localStorage.setItem('cloude.theme', 'claude');"
            f" localStorage.setItem('cloude.themeJsAllowlist', {allowlist_json});"
            " } catch (e) {}"
        )
        pg = context.new_page()
        pg.goto(live_harness)
        pg.wait_for_function("window.__themesReady !== undefined")
        pg.evaluate("window.__themesReady")

        assert pg.evaluate("document.hidden") is False, (
            "the page reports document.hidden; a backgrounded tab freezes "
            "rendering and makes every measurement here meaningless"
        )
        yield pg
        context.close()
        browser.close()


def _set_effect_status(page, status: str) -> None:
    page.evaluate(
        "(value) => { document.documentElement.dataset.themeEffects = value; }",
        status,
    )
    _settle_frames(page)


def _session_info(name: str, pin: str | None, agent: str | None) -> dict:
    return {
        "tmux_session": name,
        "pinned_theme": pin,
        "agent_type": agent,
        "label": name,
        "session": {"id": name, "working_dir": "/tmp", "pty_pid": 1},
    }


def _enter(page, info: dict, first_time: bool = False) -> None:
    method = "showTerminal" if first_time else "returnToExistingTerminal"
    page.evaluate(
        """async (args) => {
            await window.App[args.method](args.info, {});
        }""",
        {"method": method, "info": info},
    )
    _settle_frames(page)


def _settle_frames(page) -> None:
    page.evaluate(
        """() => new Promise((resolve) => {
            requestAnimationFrame(() => requestAnimationFrame(resolve));
        })"""
    )


def _xterm_theme(page) -> dict:
    return page.evaluate(
        "() => JSON.parse(JSON.stringify(window.TerminalController.term.options.theme))"
    )


def _write_blocks(page, cells: list[dict]) -> None:
    sequence = "".join(f"[{cell['sgr']}m█" for cell in cells) + "[0m"
    page.evaluate(
        """(text) => new Promise((resolve) => {
            const term = window.TerminalController.term;
            term.reset();
            term.write(text, resolve);
        })""",
        sequence,
    )
    _settle_frames(page)


def _cell_boxes(page, count: int) -> list[dict]:
    return page.evaluate(
        """(count) => {
            const term = window.TerminalController.term;
            const screen = document.querySelector('#terminal .xterm-screen');
            const rect = screen.getBoundingClientRect();
            const cellWidth = rect.width / term.cols;
            const cellHeight = rect.height / term.rows;
            const out = [];
            for (let i = 0; i < count; i++) {
                out.push({
                    x: Math.round(rect.x + (i + 0.5) * cellWidth),
                    y: Math.round(rect.y + 0.5 * cellHeight),
                });
            }
            return out;
        }""",
        count,
    )


def _empty_box(page) -> dict:
    return page.evaluate(
        """() => {
            const term = window.TerminalController.term;
            const screen = document.querySelector('#terminal .xterm-screen');
            const rect = screen.getBoundingClientRect();
            return {
                x: Math.round(rect.x + rect.width / 2),
                y: Math.round(rect.y + (rect.height / term.rows) * (term.rows - 2)),
            };
        }"""
    )


def _sample(page, points: list[dict], save_to: Path | None = None) -> list[tuple]:
    from PIL import Image  # noqa: PLC0415

    _set_effect_status(page, "inactive")

    shot = page.screenshot()
    if save_to is not None:
        save_to.write_bytes(shot)
    image = Image.open(io.BytesIO(shot)).convert("RGB")
    return [image.getpixel((point["x"], point["y"])) for point in points]


def _assert_close(actual: tuple, expected_hex: str, what: str) -> None:
    expected = _hex_to_rgb(expected_hex)
    delta = max(abs(a - b) for a, b in zip(actual, expected))
    assert delta <= CHANNEL_TOLERANCE, (
        f"{what}: rendered {actual}, expected {expected} from {expected_hex} "
        f"(per-channel difference {delta} > {CHANNEL_TOLERANCE})"
    )


class TestPinnedTerminalSurvivesItsAgent:

    def test_the_first_attach_paints_the_pin_not_the_agent(self, page, tmp_path):
        _enter(page, _session_info("cloude_a", "dracula", "claude"), first_time=True)
        _set_effect_status(page, "inactive")
        theme = _xterm_theme(page)
        assert theme["background"].lower() == DRACULA["xterm"]["background"].lower()

        pixel = _sample(page, [_empty_box(page)],
                        save_to=tmp_path / "first-attach.png")[0]
        _assert_close(pixel, DRACULA["xterm"]["background"],
                      "the terminal background on first attach")

    def test_leaving_and_returning_keeps_the_dracula_terminal(self, page, tmp_path):
        info = _session_info("cloude_a", "dracula", "claude")
        _enter(page, info, first_time=True)
        before = _sample(page, [_empty_box(page)])[0]

        page.evaluate("() => window.App.showLaunchpad()")
        _settle_frames(page)
        _enter(page, info)

        after = _sample(page, [_empty_box(page)],
                        save_to=tmp_path / "after-return.png")
        _assert_close(after[0], DRACULA["xterm"]["background"],
                      "the terminal background AFTER leaving and returning")
        assert max(abs(a - b) for a, b in zip(before, after[0])) <= CHANNEL_TOLERANCE, (
            f"the terminal changed colour across a leave and return: "
            f"{before} became {after[0]}"
        )
        assert page.evaluate("() => document.documentElement.dataset.theme") == "claude"
        assert page.evaluate(
            "() => document.getElementById('terminal-container').dataset.sessionTheme"
        ) == "dracula", "nothing may take the terminal CSS scope back"

    def test_foreground_cursor_and_ansi_swatches_are_the_dracula_manifest(
        self, page, tmp_path
    ):
        info = _session_info("cloude_a", "dracula", "claude")
        _enter(page, info, first_time=True)
        page.evaluate("() => window.App.showLaunchpad()")
        _settle_frames(page)
        _enter(page, info)

        swatches = [
            ("39", "foreground"),
            ("36", "cyan"),
            ("31", "red"),
            ("32", "green"),
            ("34", "blue"),
            ("35", "magenta"),
            ("93", "brightYellow"),
        ]
        _write_blocks(page, [{"sgr": sgr} for sgr, _ in swatches])
        boxes = _cell_boxes(page, len(swatches))
        pixels = _sample(page, boxes, save_to=tmp_path / "ansi-swatches.png")

        for (sgr, key), pixel in zip(swatches, pixels):
            _assert_close(pixel, DRACULA["xterm"][key],
                          f"SGR {sgr} ({key}) after leaving and returning")

        _set_effect_status(page, "inactive")
        assert _xterm_theme(page)["cursor"].lower() == DRACULA["xterm"]["cursor"].lower()

    def test_an_unpinned_session_renders_the_home_page_palette(self, page):
        page.evaluate("() => localStorage.setItem('cloude.theme', 'dracula')")
        page.evaluate("() => window.Themes.applyTheme('dracula', {persist: true})")
        _enter(page, _session_info("cloude_b", None, "claude"), first_time=True)

        pixel = _sample(page, [_empty_box(page)])[0]
        _assert_close(pixel, DRACULA["xterm"]["background"],
                      "an unpinned session's terminal follows the home page")
        assert page.evaluate("() => document.documentElement.dataset.theme") == "dracula", (
            "and the PAGE is the same theme - one choice, both surfaces"
        )

    def test_a_b_a_switching_lands_back_on_dracula(self, page, tmp_path):
        a = _session_info("cloude_a", "dracula", "claude")
        b = _session_info("cloude_b", "matrix", "claude")
        _enter(page, a, first_time=True)
        _enter(page, b)
        _enter(page, a)

        pixel = _sample(page, [_empty_box(page)], save_to=tmp_path / "aba.png")[0]
        _assert_close(pixel, DRACULA["xterm"]["background"], "back on session A")

    def test_the_scoped_css_variables_follow_the_new_owner(self, page):
        _enter(page, _session_info("cloude_b", "matrix", "claude"), first_time=True)
        _enter(page, _session_info("cloude_a", "dracula", "claude"))

        matrix_only = [
            name for name in MANIFESTS["matrix"].get("cssVars", {})
            if name not in DRACULA.get("cssVars", {})
        ]
        leaked = page.evaluate(
            """(names) => {
                const el = document.getElementById('terminal-container');
                return names.filter((n) => el.style.getPropertyValue(n) !== '');
            }""",
            matrix_only,
        )
        assert leaked == [], f"variables from the outgoing theme survived: {leaked}"

        sample_name = next(iter(DRACULA.get("cssVars", {})), None)
        if sample_name is not None:
            value = page.evaluate(
                "(n) => document.getElementById('terminal-container')"
                ".style.getPropertyValue(n).trim()",
                sample_name,
            )
            assert value == DRACULA["cssVars"][sample_name].strip(), (
                f"{sample_name} did not take the incoming theme's value"
            )


class TestTheOpacityAdapterIsTheOnlyTransform:

    def test_it_changes_the_background_and_nothing_else(self, page):
        _enter(page, _session_info("cloude_a", "dracula", "claude"), first_time=True)
        _set_effect_status(page, "running")

        theme = _xterm_theme(page)
        red, green, blue = _hex_to_rgb(DRACULA["xterm"]["background"])
        assert theme["background"] == f"rgba({red}, {green}, {blue}, 0.9)", (
            "the background must be the manifest colour at the adapter's "
            f"opacity, got {theme['background']}"
        )
        for key, expected in DRACULA["xterm"].items():
            if key == "background":
                continue
            assert theme[key].lower() == expected.lower(), (
                f"{key} was altered on its way to the renderer; the opacity "
                "adapter must only touch the background"
            )

    def test_an_inactive_effect_leaves_the_terminal_fully_opaque(self, page):
        _enter(page, _session_info("cloude_a", "dracula", "claude"), first_time=True)
        _set_effect_status(page, "inactive")

        theme = _xterm_theme(page)
        assert theme["background"].lower() == DRACULA["xterm"]["background"].lower(), (
            "with no animated background confirmed on screen the terminal "
            "must render at full opacity"
        )

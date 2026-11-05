
from __future__ import annotations

import functools
import http.server
import json
import os
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CLIENT = REPO / "client"
TOKENS = REPO / "web" / "src" / "opscenter" / "tokens.css"
THEMES = CLIENT / "css" / "themes"

PAGE = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="/dist/app.css"><link rel="stylesheet" href="/source-tokens.css">
</head><body data-oc-base style="margin:0;background:var(--oc-ground-page);color:var(--oc-text-primary)">
<div id="root-row" style="padding:12px"><input type="datetime-local" data-field id="root-field" value="2026-11-03T09:30"></div>
<div id="scope" data-session-theme="pinned" style="padding:12px;background:var(--oc-ground-page)">
  <input type="datetime-local" data-field id="scope-field" value="2026-11-03T09:30"></div>
<script src="/js/theme-scheme.js"></script><script src="/js/theme-var-writer.js"></script>
<script>
  const painted = { root: {}, scope: {} };
  window.paint = (rootVars, scopeVars) => {
    const w = window.ThemeVarWriter;
    if (rootVars) painted.root = w.applyVarDiff(document.documentElement.style, painted.root, rootVars).values;
    if (scopeVars) painted.scope = w.applyVarDiff(document.getElementById('scope').style, painted.scope, scopeVars).values;
    const of = (id) => getComputedStyle(document.getElementById(id)).colorScheme;
    return { root: of('root-field'), scope: of('scope-field') };
  };
</script>
</body></html>"""


def css_vars(theme: str) -> dict[str, str]:
    return json.loads((THEMES / theme / "theme.json").read_text())["cssVars"]


@pytest.fixture(scope="module")
def shots(tmp_path_factory: pytest.TempPathFactory) -> Path:
    chosen = os.environ.get("CARNIVORE_SHOTS_DIR")
    if not chosen:
        return tmp_path_factory.mktemp("color-scheme-shots")
    out = Path(chosen)
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture(scope="module")
def browser_page():
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: color-scheme was NOT measured")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            routes = {"/scheme.html": (PAGE.encode(), "text/html"), "/source-tokens.css": (TOKENS.read_bytes(), "text/css")}
            hit = routes.get(self.path.split("?")[0])
            if hit is None:
                super().do_GET()
                return
            body, kind = hit
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(CLIENT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            server.shutdown()
            pytest.skip(f"chromium unavailable: {exc}")
        pg = browser.new_page(viewport={"width": 360, "height": 140})
        pg.goto(f"http://127.0.0.1:{server.server_address[1]}/scheme.html")
        yield pg
        browser.close()
    server.shutdown()


def fresh(page) -> None:
    page.reload()
    page.wait_for_function("() => typeof window.paint === 'function'")


def test_an_unpainted_page_keeps_the_default_dark_scheme(browser_page):
    fresh(browser_page)
    assert browser_page.evaluate("getComputedStyle(document.getElementById('root-field')).colorScheme") == "dark"


@pytest.mark.parametrize(("root", "scope", "want"), [
    ("carnivore-light", "dracula", {"root": "light", "scope": "dark"}),
    ("dracula", "carnivore-light", {"root": "dark", "scope": "light"}),
    ("matrix", "metal", {"root": "dark", "scope": "dark"}),
])
def test_each_scope_takes_its_own_themes_scheme(browser_page, shots, root, scope, want):
    fresh(browser_page)
    got = browser_page.evaluate("([r, s]) => window.paint(r, s)", [css_vars(root), css_vars(scope)])
    assert got == want, f"{root} page with a {scope} session: {got}"
    browser_page.locator("#root-row").screenshot(path=str(shots / f"datetime-field-{root}.png"))


@pytest.mark.parametrize("ground", ["no such color", "transparent", "currentColor", "rgba(255, 255, 255, 0.5)", "#ffffff80"])
def test_a_scope_whose_ground_is_unreadable_or_see_through_inherits(browser_page, ground):
    fresh(browser_page)
    got = browser_page.evaluate("([r, s]) => window.paint(r, s)",
                                [css_vars("carnivore-light"), {"--color-bg-page": ground, "--color-bg": ground}])
    assert got == {"root": "light", "scope": "light"}, f"ground {ground!r}: {got}"


def test_switching_to_a_theme_with_no_ground_removes_the_old_scheme(browser_page):
    fresh(browser_page)
    first = browser_page.evaluate("([r, s]) => window.paint(r, s)", [css_vars("carnivore-light"), css_vars("dracula")])
    assert first["scope"] == "dark"
    after = browser_page.evaluate("(s) => window.paint(null, s)", {"--color-accent": "#ff0000"})
    assert after == {"root": "light", "scope": "light"}, after


def test_an_explicit_scheme_passes_through(browser_page):
    fresh(browser_page)
    got = browser_page.evaluate("([r, s]) => window.paint(r, s)", [css_vars("dracula"), {**css_vars("dracula"), "--color-scheme": "light"}])
    assert got == {"root": "dark", "scope": "light"}, got


def test_the_page_ground_wins_over_the_card_ground(browser_page):
    fresh(browser_page)
    got = browser_page.evaluate("([r, s]) => window.paint(r, s)",
                                [css_vars("dracula"), {"--color-bg-page": "#eceeef", "--color-bg": "#000000"}])
    assert got["scope"] == "light", got

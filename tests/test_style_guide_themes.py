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
        "playwright is not installed, so NOTHING about how the style guide "
        "renders was measured. This is a could-not-evaluate, not a pass."
    ),
)

from src.security_headers import SECURITY_HEADERS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_ROOT = REPO_ROOT / "client"
THEMES_DIR = CLIENT_ROOT / "css" / "themes"

THEMES = ("carnivore", "carnivore-light", "dracula")

CONTRAST_SAMPLES = (
    ".sg-h2",
    ".sg-h3",
    ".sg-lead",
    ".sg-section p",
    ".sg-facts > dt",
    ".sg-toc__link",
    ".sg-caption",
    ".sg-specimen__label",
    ".pl-title",
    ".pl-label",
    ".modal-btn-confirm",
    ".restart-picker__title",
    ".restart-picker__verb",
    ".modal-btn-secondary",
    ".session-row-menu__label",
    ".toast__title-text",
    ".settings-field-label",
)

KNOWN_BELOW_AA: dict[tuple[str, str], float] = {}

_MANIFESTS = [
    dict(json.loads(p.read_text(encoding="utf-8")), source="builtin")
    for p in sorted(THEMES_DIR.glob("*/theme.json"))
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _GuideHandler(http.server.SimpleHTTPRequestHandler):

    def translate_path(self, path: str) -> str:  # noqa: D102
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/static/"):
            return str(CLIENT_ROOT / clean[len("/static/"):])
        return str(CLIENT_ROOT / "__nothing_here__")

    def end_headers(self) -> None:  # noqa: D102
        for header, value in SECURITY_HEADERS.items():
            self.send_header(header, value)
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/v1/themes":
            body = json.dumps(_MANIFESTS).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def guess_type(self, path):  # noqa: D102
        if str(path).endswith(".js"):
            return "text/javascript"
        return super().guess_type(path)

    def log_message(self, *args) -> None:  # noqa: D102
        return


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), _GuideHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium could not launch ({exc}); the style guide was NOT measured")
        yield chromium
        chromium.close()


def _open(browser, base_url: str, theme: str):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors: list[str] = []
    api_requests: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("request", lambda req: api_requests.append(req.url) if "/api/" in req.url else None)
    page.add_init_script(
        "window.__csp = [];"
        "document.addEventListener('securitypolicyviolation',"
        " (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
    )
    suffix = "" if theme == "carnivore" else f"?theme={theme}"
    page.goto(f"{base_url}/static/style-guide.html{suffix}", wait_until="load")
    page.wait_for_selector("html[data-sg-mounted='true']", state="attached", timeout=20000)
    page.wait_for_selector(f"html[data-sg-theme='{theme}']", state="attached", timeout=20000)
    _settle(page)
    return page, errors, api_requests, page.evaluate("window.__csp")


def _settle(page) -> None:
    page.evaluate(
        "() => Promise.all(document.getAnimations()"
        ".filter((a) => a.constructor.name === 'CSSTransition')"
        ".map((a) => a.finished.catch(() => null)))"
    )


def _resolved_accent(page) -> str:
    return page.evaluate("window.StyleGuide.resolved('--oc-orange')")


def _manifest_accent(page, theme: str) -> str:
    raw = next(m for m in _MANIFESTS if m["id"] == theme)["cssVars"]["--color-accent"]
    return page.evaluate(
        "(c) => { const s = document.createElement('span'); s.style.color = c;"
        " document.body.append(s); const v = getComputedStyle(s).color; s.remove(); return v; }",
        raw,
    )


_CONTRAST_JS = """
(selectors) => {
  // ANY css colour to sRGB bytes through a 1x1 canvas. getComputedStyle
  // hands back rgb(), color(srgb ...) or oklab(...) depending on how the
  // value was written (color-mix serialises in its mixing space), and only
  // the canvas converts all of them to one space.
  const ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  const parts = (css) => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = css;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return { rgb: [d[0] / 255, d[1] / 255, d[2] / 255], alpha: d[3] / 255 };
  };
  const lum = (css) => {
    const c = parts(css).rgb.map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  // The nearest ancestor ground that is (nearly) opaque: what the text sits on.
  const ground = (el) => {
    for (let node = el; node; node = node.parentElement) {
      const bg = getComputedStyle(node).backgroundColor;
      if (bg !== 'transparent' && parts(bg).alpha > 0.9) return bg;
    }
    return getComputedStyle(document.documentElement).backgroundColor;
  };
  const out = [];
  for (const sel of selectors) {
    const els = [...document.querySelectorAll(sel)].filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && el.textContent.trim() && !el.closest('[disabled], .is-unavailable');
    }).slice(0, 6);
    if (!els.length) { out.push({ sel, missing: true }); continue; }
    for (const el of els) {
      const fg = getComputedStyle(el).color;
      const bg = ground(el);
      const l1 = lum(fg); const l2 = lum(bg);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      out.push({ sel, text: el.textContent.trim().slice(0, 40), fg, bg, ratio: Math.round(ratio * 100) / 100 });
    }
  }
  return out;
}
"""


@pytest.mark.parametrize("theme", THEMES)
def test_the_guide_renders_every_section_and_specimen(browser, base_url: str, theme: str) -> None:
    page, errors, api_requests, csp = _open(browser, base_url, theme)
    try:
        sections = page.evaluate("document.querySelectorAll('.sg-section').length")
        expected = len(json.loads((CLIENT_ROOT / "style-guide" / "registry.json").read_text())["sections"])
        assert sections == expected, f"{sections} of {expected} sections rendered"
        states = page.evaluate(
            "[...document.querySelectorAll('[id^=sg-live-]')].map((el) =>"
            " [el.id, el.dataset.sgState || 'none', el.childElementCount])"
        )
        assert len(states) > 15, f"only {len(states)} live containers found"
        broken = [s for s in states if s[1] != "mounted" or s[2] == 0]
        assert not broken, f"specimens that did not mount or render nothing: {broken}"
        assert not errors, f"page errors under {theme}: {errors}"
        assert not csp, f"CSP violations under {theme}: {csp}"
        assert page.evaluate("!document.documentElement.dataset.sgFailed")
        stray = [u for u in api_requests if not u.split("?", 1)[0].endswith("/api/v1/themes")]
        assert not stray, f"the guide reached the API beyond the theme list: {stray}"
        assert page.evaluate("document.documentElement.dataset.theme") == theme
    finally:
        page.context.close()


@pytest.mark.parametrize("theme", THEMES)
def test_key_text_meets_wcag_aa(browser, base_url: str, theme: str) -> None:
    page, _errors, _api, _csp = _open(browser, base_url, theme)
    try:
        results = page.evaluate(_CONTRAST_JS, list(CONTRAST_SAMPLES))
        missing = [r["sel"] for r in results if r.get("missing")]
        assert not missing, f"contrast samples matched nothing (the check looked at nothing): {missing}"
        low = [r for r in results if not r.get("missing") and r["ratio"] < 4.5]
        known = {sel for (t, sel) in KNOWN_BELOW_AA if t == theme}
        unexpected = [r for r in low if r["sel"] not in known]
        assert not unexpected, f"text below WCAG AA under {theme}: " + json.dumps(unexpected, indent=1)
        for sel in known:
            still = [r for r in low if r["sel"] == sel]
            assert still, (
                f"{sel} now meets AA under {theme}: remove it from KNOWN_BELOW_AA"
            )
    finally:
        page.context.close()


def test_the_switcher_repaints_through_the_theme_registry(browser, base_url: str) -> None:
    page, errors, _api, _csp = _open(browser, base_url, "carnivore")
    try:
        assert _resolved_accent(page) == _manifest_accent(page, "carnivore")
        stored_before = page.evaluate("localStorage.getItem('carnivore.theme')")
        options = page.evaluate("[...document.querySelectorAll('#sg-theme-select option')].length")
        assert options == len(_MANIFESTS), f"picker lists {options} of {len(_MANIFESTS)} themes"
        for theme in ("dracula", "carnivore-light"):
            page.select_option("#sg-theme-select", theme)
            page.wait_for_selector(f"html[data-theme='{theme}']", state="attached")
            _settle(page)
            assert _resolved_accent(page) == _manifest_accent(page, theme), theme
            cell = page.evaluate(
                "document.querySelector('[data-sg-token=\"--oc-orange\"] .sg-token__value').textContent"
            )
            assert cell == _resolved_accent(page)
        assert _resolved_accent(page) != _manifest_accent(page, "carnivore")
        saved = page.evaluate("localStorage.getItem('carnivore.theme')")
        assert saved == stored_before, f"the guide saved a theme choice: {stored_before} became {saved}"
        assert not errors, errors
    finally:
        page.context.close()


def test_negative_control_the_contrast_probe_can_fail(browser, base_url: str) -> None:
    page, _errors, _api, _csp = _open(browser, base_url, "carnivore")
    try:
        page.evaluate(
            "() => { const p = document.createElement('p'); p.className = 'sg-negative';"
            " p.textContent = 'barely there'; p.style.color = 'var(--oc-ground-panel)';"
            " document.querySelector('.sg-section').prepend(p); }"
        )
        results = page.evaluate(_CONTRAST_JS, [".sg-negative"])
        assert results and results[0]["ratio"] < 1.5, results
    finally:
        page.context.close()

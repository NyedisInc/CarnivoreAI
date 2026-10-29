
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT_DIR = Path(__file__).resolve().parent.parent
CLIENT_DIR = REPO_ROOT_DIR / "client"
INDEX_HTML = CLIENT_DIR / "index.html"

_REMOTE_SUBRESOURCE = re.compile(
    r"""<(?:script|link|img|iframe|source|audio|video)\b[^>]*?"""
    r"""\b(?:src|href)\s*=\s*["'](https?://[^"']+)["']""",
    re.IGNORECASE | re.DOTALL,
)


def _index_html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_index_html_exists() -> None:
    assert INDEX_HTML.is_file(), f"missing {INDEX_HTML}"


def test_index_html_loads_no_remote_subresource() -> None:
    remote = _REMOTE_SUBRESOURCE.findall(_index_html())
    assert remote == [], (
        "client/index.html loads these off-origin subresources: "
        f"{remote}. vendor them under client/vendor/<lib>/ and serve from "
        "/static instead. see CLAUDE.md, security posture."
    )


def test_index_html_mentions_no_cdn_host() -> None:
    html = re.sub(r"<!--.*?-->", "", _index_html(), flags=re.DOTALL)
    assert "cdn.jsdelivr.net" not in html, (
        "cdn.jsdelivr.net reappeared in client/index.html outside a comment"
    )


@pytest.mark.parametrize(
    "asset",
    [
        "xterm.css",
        "xterm.js",
        "xterm-addon-fit.js",
        "xterm-addon-webgl.js",
        "xterm-addon-unicode11.js",
        "xterm-addon-search.js",
    ],
)
def test_vendored_xterm_asset_present_and_referenced(asset: str) -> None:
    path = CLIENT_DIR / "vendor" / "xterm" / asset
    assert path.is_file(), f"missing vendored asset {path}"
    assert path.stat().st_size > 0, f"vendored asset is empty: {path}"
    assert f"/static/vendor/xterm/{asset}" in _index_html(), (
        f"{asset} is vendored but index.html does not reference it"
    )


def test_vendored_xterm_has_version_doc() -> None:
    version_md = CLIENT_DIR / "vendor" / "xterm" / "VERSION.md"
    assert version_md.is_file(), f"missing {version_md}"
    text = version_md.read_text(encoding="utf-8")
    assert "5.3.0" in text, "VERSION.md must pin the xterm version"



DIST_DIR = CLIENT_DIR / "dist"

_REMOTE_LOAD = re.compile(
    r"""(?:
        <a\b[^>]*?\bhref\s*=\s*["']https?://[^"']+["']  # SEE BELOW: not a load
      | \bfrom\s*["'](https?://[^"']+)["']          # static import
      | \bimport\s*\(\s*["'](https?://[^"']+)["']   # dynamic import
      | \bimportScripts\s*\(\s*["'](https?://[^"']+)["']
      | \bnew\s+Worker\s*\(\s*["'](https?://[^"']+)["']
      | \b(?:src|href)\s*=\s*["'](https?://[^"']+)["']
      | @import\s+(?:url\()?["']?(https?://[^"')\s]+)
      | \burl\(\s*["']?(https?://[^"')]+)
    )""",
    re.IGNORECASE | re.VERBOSE,
)


_EVAL_SHAPED = re.compile(r"(?<![.\w$])eval\s*\(|new\s+Function\s*\(")


def _dist_files() -> list[Path]:
    if not DIST_DIR.is_dir():
        return []
    return sorted(p for p in DIST_DIR.rglob("*") if p.is_file())


def test_the_remote_load_scanner_can_actually_fail() -> None:
    def hits(text: str) -> list[str]:
        return [u for match in _REMOTE_LOAD.findall(text) for u in match if u]

    assert hits('<link rel="stylesheet" href="https://fonts.googleapis.com/x">')
    assert hits('<script src="https://cdn.jsdelivr.net/x.js"></script>')
    assert hits('import x from "https://esm.sh/x";')
    assert hits('new Worker("https://example.com/w.js")')
    assert hits('@import url("https://example.com/a.css");')
    assert hits('background: url(https://example.com/a.png)')
    assert hits('<a href="https://nyedis.ai" target="_blank">x</a>') == []
    assert hits('<a class="home-bar__link" href="https://nyedis.ai">x</a>') == []
    assert hits('<link href="https://nyedis.ai">')


def test_the_built_bundle_is_committed() -> None:
    names = {p.name for p in _dist_files()}
    assert names, (
        f"{DIST_DIR} is empty or absent. Build it: cd web && npm ci && npm run "
        "build, then commit client/dist. See CLAUDE.md, 'The web/ build'."
    )
    assert {"app.js", "app.css"} <= names, (
        "the bundle must emit the fixed names app.js and app.css that "
        f"client/index.html references; found {sorted(names)}"
    )


@pytest.mark.parametrize(
    "face",
    [
        "JetBrainsMono-Regular.woff2",
        "JetBrainsMono-Medium.woff2",
        "JetBrainsMono-Bold.woff2",
    ],
)
def test_vendored_dashboard_face_present_and_referenced(face: str) -> None:
    path = CLIENT_DIR / "fonts" / "jetbrains-mono" / face
    assert path.is_file(), f"missing vendored face {path}"
    assert path.stat().st_size > 0, f"vendored face is empty: {path}"
    css = (DIST_DIR / "app.css").read_text(encoding="utf-8")
    assert f"/static/fonts/jetbrains-mono/{face}" in css, (
        f"{face} is vendored but client/dist/app.css does not use it"
    )


def test_vendored_dashboard_face_has_its_licence() -> None:
    ofl = CLIENT_DIR / "fonts" / "jetbrains-mono" / "OFL.txt"
    assert ofl.is_file(), f"missing {ofl}"
    assert ofl.stat().st_size > 0, f"licence file is empty: {ofl}"


def test_index_html_loads_the_bundle() -> None:
    html = _index_html()
    assert '<script type="module" src="/static/dist/app.js">' in html, (
        "client/index.html does not load the compiled bundle as a module"
    )
    assert '/static/dist/app.css' in html, (
        "client/index.html does not load the compiled stylesheet"
    )
    assert "/static/dist/opscenter." not in html, (
        "client/index.html still loads the retired second bundle; the "
        "dashboard is inside app.js and app.css now"
    )


@pytest.mark.parametrize("name", ["app.js", "app.css"])
def test_bundle_loads_nothing_off_origin(name: str) -> None:
    path = DIST_DIR / name
    if not path.is_file():
        pytest.fail(f"missing {path}; build web/ and commit client/dist")
    found = [
        url
        for match in _REMOTE_LOAD.findall(path.read_text(encoding="utf-8"))
        for url in match
        if url
    ]
    assert found == [], (
        f"client/dist/{name} loads these off-origin resources: {found}. "
        "vendor the dependency into the bundle instead; the CSP is "
        "default-src 'self' and a content blocker drops the rest anyway. "
        "see CLAUDE.md, security posture."
    )


def _dist_js() -> list[Path]:
    return sorted(DIST_DIR.glob("*.js")) if DIST_DIR.is_dir() else []


def _eval_hits(path: Path) -> list[str]:
    return _EVAL_SHAPED.findall(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", _dist_js() or [DIST_DIR / "app.js"], ids=lambda p: p.name)
def test_bundle_contains_no_eval(path: Path) -> None:
    if not path.is_file():
        pytest.fail(f"missing {path}; build web/ and commit client/dist")
    hits = _eval_hits(path)
    assert hits == [], (
        f"client/dist/{path.name} contains {len(hits)} eval-shaped construct(s). "
        "The CSP has no 'unsafe-eval' and must not gain one; change the "
        "build target or drop the dependency that needs it."
    )


def test_eval_guard_covers_every_dist_script_and_goes_red(tmp_path: Path) -> None:
    assert {"app.js", "popout.js", "style-guide.js"} <= {p.name for p in _dist_js()}
    planted = tmp_path / "popout.js"
    planted.write_text("var f=new Function('return 1');", encoding="utf-8")
    assert _eval_hits(planted) != []
    assert _eval_hits(DIST_DIR / "popout.js") == []


def test_the_bundle_detectors_can_actually_fail() -> None:
    assert _REMOTE_LOAD.search('import x from "https://cdn.example/x.js"')
    assert _REMOTE_LOAD.search('@import url("https://fonts.example/f.css");')
    assert _REMOTE_LOAD.search("a{background:url(https://cdn.example/i.png)}")
    assert _REMOTE_LOAD.search('<script src="https://cdn.jsdelivr.net/x.js">')
    assert _EVAL_SHAPED.search("eval(payload)")
    assert _EVAL_SHAPED.search("new Function('return 1')")
    assert not _REMOTE_LOAD.search('throw new Error("https://svelte.dev/e/x")')
    assert not _REMOTE_LOAD.search('createElementNS("http://www.w3.org/1999/xhtml")')
    assert not _EVAL_SHAPED.search("o.eval_(x)")
    assert not _EVAL_SHAPED.search("this.reevaluate(x)")



ADMIN_DIST_DIR = REPO_ROOT_DIR / "hosted" / "catalog" / "admin" / "dist"


def test_the_admin_bundle_is_committed() -> None:
    names = {p.name for p in ADMIN_DIST_DIR.glob("*") if p.is_file()}
    assert {"index.html", "admin.js", "admin.css"} <= names, (
        "hosted/catalog/admin/dist must carry index.html, admin.js and "
        f"admin.css; found {sorted(names)}. Build it: cd web && npm ci && "
        "npm run admin:build, then commit the bundle."
    )


@pytest.mark.parametrize("name", ["index.html", "admin.js", "admin.css"])
def test_admin_bundle_loads_nothing_off_origin(name: str) -> None:
    path = ADMIN_DIST_DIR / name
    if not path.is_file():
        pytest.fail(f"missing {path}; build web/src/admin and commit the bundle")
    found = [
        url
        for match in _REMOTE_LOAD.findall(path.read_text(encoding="utf-8"))
        for url in match
        if url
    ]
    assert found == [], (
        f"hosted/catalog/admin/dist/{name} loads these off-origin resources: "
        f"{found}. The CSP served for /admin/* is default-src 'none' with "
        "script-src 'self', so the browser refuses every one of them."
    )


def test_admin_bundle_contains_no_eval() -> None:
    path = ADMIN_DIST_DIR / "admin.js"
    if not path.is_file():
        pytest.fail(f"missing {path}; build web/src/admin and commit the bundle")
    hits = _EVAL_SHAPED.findall(path.read_text(encoding="utf-8"))
    assert hits == [], (
        f"hosted/catalog/admin/dist/admin.js contains {len(hits)} eval-shaped "
        "construct(s); the /admin/* CSP has no 'unsafe-eval'."
    )



STYLE_GUIDE_FILES = sorted(
    [CLIENT_DIR / "style-guide.html"]
    + [p for p in (CLIENT_DIR / "style-guide").rglob("*") if p.is_file()]
)


def test_the_style_guide_exists() -> None:
    names = {p.name for p in STYLE_GUIDE_FILES}
    assert {"style-guide.html", "guide.js", "guide.css", "registry.json"} <= names, names


@pytest.mark.parametrize("path", STYLE_GUIDE_FILES, ids=lambda p: p.relative_to(CLIENT_DIR).as_posix())
def test_style_guide_loads_nothing_off_origin(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    hits = [u for match in _REMOTE_LOAD.findall(text) for u in match if u]
    hits += _REMOTE_SUBRESOURCE.findall(text)
    assert not hits, f"{path.name} loads off-origin: {hits}"
    assert not _EVAL_SHAPED.search(text), f"{path.name} carries an eval-shaped call"

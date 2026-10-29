
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "hosted" / "catalog" / "admin" / "dist"
INDEX = DIST_DIR / "index.html"
SCRIPT = DIST_DIR / "admin.js"
STYLES = DIST_DIR / "admin.css"
SOURCE_DIR = REPO_ROOT / "web" / "src" / "admin"

_INLINE_SCRIPT = re.compile(
    r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(?!\s*</script>)", re.IGNORECASE
)

_ON_ATTRIBUTE = re.compile(r"<[^>]*\son[a-z]+\s*=\s*[\"']", re.IGNORECASE)

_EVAL_SHAPED = re.compile(r"(?<![.\w$])eval\s*\(|new\s+Function\s*\(")

_ABSOLUTE_API = re.compile(r"https?://[^\"'\s]*/(?:api/)?v1\b/?", re.IGNORECASE)

_API_BASE = "https://api.carnivore.ai/v1"

_CATALOG_PLACEHOLDERS = {"https://host/v1"}

_KEY_LITERAL = r"'(admin\.[a-z0-9_.]*[a-z0-9_])'"

_POOL_ID = re.compile(r"\b[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]{8,}\b")
_JWT_SHAPED = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.fail(
            f"missing {path}. Build it: cd web && npm ci && npm run admin:build, "
            "then commit hosted/catalog/admin/dist."
        )
    return path.read_text(encoding="utf-8")


def test_the_three_emitted_files_are_committed() -> None:
    names = {p.name for p in DIST_DIR.glob("*") if p.is_file()}
    assert {"index.html", "admin.js", "admin.css"} <= names, (
        "the admin build must emit index.html, admin.js and admin.css; "
        f"found {sorted(names)}"
    )


def test_the_document_references_its_assets_relatively() -> None:
    html = _read(INDEX)
    assert 'src="./admin.js"' in html, "index.html does not load ./admin.js relatively"
    assert 'href="./admin.css"' in html, "index.html does not load ./admin.css relatively"
    assert 'src="/admin.js"' not in html and 'src="/admin/' not in html, (
        "index.html references an asset from the site root; the page is "
        "served from /admin/ and `base` must stay './'"
    )


def test_the_document_carries_no_inline_script_and_no_event_attribute() -> None:
    html = _read(INDEX)
    assert _INLINE_SCRIPT.findall(html) == [], (
        "index.html carries an inline <script>. The /admin/* CSP is "
        "script-src 'self' with no nonce, so the browser refuses it."
    )
    assert _ON_ATTRIBUTE.findall(html) == [], (
        "index.html carries an on* event attribute, which script-src 'self' refuses"
    )


def test_the_bundle_contains_no_eval() -> None:
    hits = _EVAL_SHAPED.findall(_read(SCRIPT))
    assert hits == [], (
        f"admin.js contains {len(hits)} eval-shaped construct(s). The CSP has "
        "no 'unsafe-eval' and must not gain one."
    )


def test_the_bundle_never_writes_durable_browser_storage() -> None:
    text = _read(SCRIPT)
    assert "localStorage" not in text, (
        "admin.js references localStorage. The one credential this page "
        "holds must die with the tab; see web/src/admin/admin-host.svelte.ts."
    )
    assert "sessionStorage" in text, (
        "admin.js references no sessionStorage at all, so the assertion "
        "above is passing for the wrong reason"
    )


def test_the_bundle_talks_to_exactly_one_api_base() -> None:
    text = _read(SCRIPT)
    assert _API_BASE in text, "admin.js carries no api base at all"
    assert set(_ABSOLUTE_API.findall(text)) - _CATALOG_PLACEHOLDERS == {_API_BASE}, (
        "admin.js names an api base other than " + _API_BASE
    )
    assert "/api/v1" not in text, "admin.js still carries the relative /api/v1 prefix"


def test_the_bundle_carries_no_credential_shaped_string() -> None:
    text = _read(SCRIPT)
    assert _POOL_ID.findall(text) == [], "admin.js contains a cognito pool id"
    assert _JWT_SHAPED.findall(text) == [], "admin.js contains a jwt-shaped string"


def test_every_admin_key_the_source_names_is_in_the_one_catalog() -> None:
    catalog = (REPO_ROOT / "client" / "js" / "i18n" / "catalog.en.js").read_text(
        encoding="utf-8"
    )
    present = set(re.findall(r"'(admin\.[a-z0-9_.]+)':", catalog))
    assert len(present) > 30, "the admin.* block is missing from the catalog"

    named: set[str] = set()
    for path in [*SOURCE_DIR.rglob("*.ts"), *SOURCE_DIR.rglob("*.svelte")]:
        if path.name.endswith(".test.ts"):
            continue
        named |= set(re.findall(_KEY_LITERAL, path.read_text("utf-8")))
    labels = (REPO_ROOT / "client" / "js" / "labels" / "admin.js").read_text("utf-8")
    named |= set(re.findall(_KEY_LITERAL, labels))

    missing = sorted(named - present)
    assert missing == [], (
        f"these admin keys are named in the source but not in the one "
        f"catalog: {missing}"
    )


def test_the_detectors_can_actually_fail() -> None:
    assert _INLINE_SCRIPT.search('<script type="module">alert(1)</script>')
    assert _INLINE_SCRIPT.search("<script>x</script>")
    assert not _INLINE_SCRIPT.search('<script type="module" src="./admin.js"></script>')

    assert _ON_ATTRIBUTE.search('<button onclick="go()">x</button>')
    assert _ON_ATTRIBUTE.search("<img onerror='x'>")
    assert not _ON_ATTRIBUTE.search('<button type="button">x</button>')

    assert _EVAL_SHAPED.search("eval(payload)")
    assert _EVAL_SHAPED.search("new Function('return 1')")
    assert not _EVAL_SHAPED.search("o.eval_(x)")

    assert _ABSOLUTE_API.search('fetch("https://catalog.carnivore.ai/api/v1/me")')
    assert _ABSOLUTE_API.search("http://localhost:3000/v1/users")
    assert set(_ABSOLUTE_API.findall('a="https://evil.example/v1" b="https://api.carnivore.ai/v1"')) != {_API_BASE}
    assert set(_ABSOLUTE_API.findall('const API_BASE = "https://api.carnivore.ai/v1";')) == {_API_BASE}
    assert not _ABSOLUTE_API.search("https://svelte.dev/e/effect_orphan")

    assert _POOL_ID.search("us-east-1_MqS0DFq6m")
    assert not _POOL_ID.search("us-east-1")
    assert _JWT_SHAPED.search("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0")
    assert not _JWT_SHAPED.search("eyJshort.a")

    assert re.findall(_KEY_LITERAL, "t('admin.title')") == ["admin.title"]
    assert re.findall(_KEY_LITERAL, "'admin.refused.' + code") == []


def test_the_stylesheet_is_not_empty() -> None:
    assert len(_read(STYLES).strip()) > 200, "admin.css is empty or near empty"

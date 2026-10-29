
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lazyload_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lazyload_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import pytest
from fastapi.testclient import TestClient

from tests.helpers.guard_fold import assert_no_offenders

from src.main import app

CLIENT_DIR = ROOT / "client"
INDEX_HTML = CLIENT_DIR / "index.html"
MODULE_FAMILIES_JS = CLIENT_DIR / "js" / "module-families.js"

EXPECTED_EAGER = [
    "/static/js/module-loader.js",
    "/static/js/module-families.js",
    "/static/js/config-editor-loader.js",
]

EXPECTED_NOT_EAGER = [
    "/static/js/config-editor-panel.js",
    "/static/js/config-editor-modal.js",
    "/static/vendor/codemirror/codemirror-bundle.js",
]

_SCRIPT_SRC_RX = re.compile(r'<script\s+src="([^"]+)"\s*>\s*</script>')


def _index_html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _eager_script_urls() -> set[str]:
    return set(_SCRIPT_SRC_RX.findall(_index_html()))


def _family_urls() -> dict[str, list[str]]:
    src = MODULE_FAMILIES_JS.read_text(encoding="utf-8")
    families: dict[str, list[str]] = {}
    for name in ("CONFIG_EDITOR",):
        block_match = re.search(
            r"var\s+" + name + r"\s*=\s*\[(.*?)\];", src, re.DOTALL
        )
        assert block_match, f"could not find the {name} array in module-families.js"
        urls = re.findall(r"'([^']+)'", block_match.group(1))
        assert urls, f"{name} array in module-families.js parsed to zero URLs"
        families[name] = urls
    return families


def test_module_families_js_exists() -> None:
    assert MODULE_FAMILIES_JS.is_file(), f"missing {MODULE_FAMILIES_JS}"


def test_eager_file_still_loads_unconditionally() -> None:
    eager = _eager_script_urls()

    def check(url: str) -> None:
        assert url in eager, "must stay in client/index.html's eager <script> list"

    assert_no_offenders("eager file still eager", EXPECTED_EAGER, check)


def test_lazy_family_member_is_no_longer_eager() -> None:
    eager = _eager_script_urls()

    def check(url: str) -> None:
        assert url not in eager, (
            "is still an eager <script> tag in client/index.html - it "
            "belongs only in client/js/module-families.js now, or it will "
            "load twice and initialise twice"
        )

    assert_no_offenders("lazy member no longer eager", EXPECTED_NOT_EAGER, check)


def test_every_family_url_is_absent_from_the_eager_list() -> None:
    eager = _eager_script_urls()
    families = _family_urls()
    for family_name, urls in families.items():
        overlap = eager.intersection(urls)
        assert not overlap, (
            f"{family_name} URL(s) {sorted(overlap)} are still eager in "
            "index.html as well as listed for lazy loading"
        )


def test_every_family_url_resolves_to_a_real_file_on_disk() -> None:
    families = _family_urls()
    for family_name, urls in families.items():
        for u in urls:
            assert u.startswith("/static/"), f"{family_name} url {u} is not same-origin under /static/"
            rel = u[len("/static/"):]
            path = CLIENT_DIR / rel
            assert path.is_file(), (
                f"{family_name} lists {u} but {path} does not exist - "
                "module-families.js has drifted from the real file tree"
            )
            assert path.stat().st_size > 0, f"{path} exists but is empty"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_every_family_url_is_served_by_the_app(client: TestClient) -> None:
    def check(member: tuple[str, str]) -> None:
        family_name, url = member
        resp = client.get(url)
        assert resp.status_code == 200, f"{family_name} member did not serve: {resp.status_code}"
        assert len(resp.content) > 0, f"{family_name} member served an empty body"

    assert_no_offenders(
        "every family url is served",
        [(name, u) for name, urls in _family_urls().items() for u in urls],
        check, label=lambda m: m[1],
    )


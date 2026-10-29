
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_routes_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_routes_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CLIENT_JS = ROOT / "client" / "js"
WEB_SRC = ROOT / "web" / "src"
API_PREFIX = "/api/v1"

MIN_CALL_SITES = 30


def _normalise(path: str) -> str:
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    path = path.split("?", 1)[0]
    path = re.sub(r"\{[^}]*\}", "{}", path)
    path = re.sub(r"(?<!/)\{\}", "", path)
    return path.rstrip("/") or "/"


def _client_call_sites() -> set[str]:
    found: set[str] = set()
    sources = list(CLIENT_JS.rglob("*.js"))
    for pattern in ("*.ts", "*.svelte"):
        sources += [
            p for p in WEB_SRC.rglob(pattern)
            if ".test." not in p.name
        ]
    for js in sorted(sources):
        src = js.read_text(encoding="utf-8", errors="replace")
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        src = re.sub(r"(?m)^\s*//.*$", "", src)

        for m in re.finditer(
                r"""\bthis\.call\(\s*['"`](/(?:[^'"`$]|\$\{[^}]*\})*)['"`]""", src):
            found.add(_normalise(API_PREFIX + m.group(1)))
        for m in re.finditer(r"""['"`](/api/v1/[^'"`\s]*)['"`]""", src):
            found.add(_normalise(m.group(1)))
        for m in re.finditer(
            r"""['"`](/api/v1/[^'"`\s]*/)['"`]\s*\+[^;]*?\+\s*['"`](/[^'"`\s]*)['"`]""",
            src,
        ):
            found.add(_normalise(m.group(1) + "{}" + m.group(2)))

    return {p for p in found if p and p != API_PREFIX}


def _server_paths() -> set[str]:
    from src.main import app

    return {_normalise(p) for p in app.openapi()["paths"]}


def test_extractor_actually_extracts() -> None:
    sites = _client_call_sites()
    assert len(sites) >= MIN_CALL_SITES, (
        f"only {len(sites)} client call sites extracted (floor {MIN_CALL_SITES}). "
        "The extractor is probably no longer matching how this client calls the "
        "API - fix the extractor, do not lower the floor."
    )
    assert "/api/v1/sessions" in sites


def test_server_route_table_is_readable() -> None:
    paths = _server_paths()
    assert len(paths) >= 20, (
        f"only {len(paths)} server paths resolved - the route table could not be "
        "read, so this file can assert nothing. This is a CANNOT DETERMINE, "
        "never a pass."
    )


def test_every_route_the_client_calls_exists_on_the_server() -> None:
    called = _client_call_sites()
    served = _server_paths()
    missing = sorted(p for p in called if p not in served)
    assert not missing, (
        "the client calls paths the server does not route: "
        + ", ".join(missing)
        + ". Either the route was renamed and the client was not updated, or the "
        "client gained a call site the server never grew."
    )


def test_the_sessions_route_the_404_was_reported_on_is_routable() -> None:
    from src.main import app

    ops = app.openapi()["paths"].get("/api/v1/sessions")
    assert ops is not None, "GET /api/v1/sessions is no longer routed"
    assert "get" in ops, "/api/v1/sessions no longer accepts GET"


@pytest.mark.parametrize(
    "path",
    ["/api/v1/sessions", "/api/v1/sessions/list", "/api/v1/sessions/attachable"],
)
def test_named_session_routes_stay_routable(path: str) -> None:
    assert _normalise(path) in _server_paths(), f"{path} is no longer routed"


def test_the_web_src_arm_actually_fires(tmp_path, monkeypatch):
    fake = tmp_path / "web-src"
    (fake / "lib").mkdir(parents=True)
    (fake / "lib" / "planted.ts").write_text(
        "export const go = () => fetch('/api/v1/planted/ts/route');\n",
        encoding="utf-8",
    )
    (fake / "lib" / "Planted.svelte").write_text(
        "<script>fetch('/api/v1/planted/svelte/route');</script>\n",
        encoding="utf-8",
    )
    (fake / "lib" / "ignored.test.ts").write_text(
        "it('x', () => fetch('/api/v1/planted/from/a/test'));\n",
        encoding="utf-8",
    )
    (fake / "lib" / "prose.ts").write_text(
        "// see /api/v1/planted/in/a/comment for why\nexport const x = 1;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("tests.test_client_called_routes_exist.WEB_SRC", fake)

    found = _client_call_sites()

    assert "/api/v1/planted/ts/route" in found, (
        "the web/src arm did not report a planted .ts call site; it is "
        "pointed at the wrong tree or matching the wrong shape"
    )
    assert "/api/v1/planted/svelte/route" in found, (
        "the web/src arm did not report a planted .svelte call site"
    )
    assert "/api/v1/planted/from/a/test" not in found, (
        "a web/src TEST file was scanned as if it were a call site"
    )
    assert "/api/v1/planted/in/a/comment" not in found, (
        "a path named in a comment was read as a call site"
    )

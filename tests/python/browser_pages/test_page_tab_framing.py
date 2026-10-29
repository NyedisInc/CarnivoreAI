
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pt_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pt_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src import security_headers as sh  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
POPOUT = "/static/popout.html"
WIDGET_LAB = "/static/dist/widget-lab/index.html"


def _directives(csp: str) -> dict:
    out = {}
    for part in csp.split(";"):
        name, _, value = part.strip().partition(" ")
        if name:
            out[name] = value.strip()
    return out


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from src.main import app

    return TestClient(app)


def test_the_frameable_list_is_exactly_the_popout_page_and_the_widget_lab_frame():
    assert sh.SELF_FRAMEABLE_PATHS == frozenset({POPOUT, WIDGET_LAB})
    assert _directives(sh.csp_for_path(WIDGET_LAB))["frame-ancestors"] == "'self'"
    assert _directives(sh.csp_for_path(POPOUT))["frame-ancestors"] == "'self'"
    assert _directives(sh.CONTENT_SECURITY_POLICY)["frame-ancestors"] == "'none'"


def test_the_frameable_policy_differs_only_in_framing_and_names_no_origin():
    framed, plain = _directives(sh.CONTENT_SECURITY_POLICY_SELF_FRAMEABLE), _directives(sh.CONTENT_SECURITY_POLICY)
    assert {k: v for k, v in framed.items() if k != "frame-ancestors"} == {k: v for k, v in plain.items() if k != "frame-ancestors"}
    for value in framed.values():
        assert "http:" not in value and "https:" not in value and "*" not in value


def test_every_route_and_static_file_but_the_popout_keeps_none(client):
    paths = {getattr(route, "path", "") for route in client.app.routes}
    paths |= {"/static/" + p.relative_to(ROOT / "client").as_posix() for p in (ROOT / "client").rglob("*.html")}
    assert POPOUT in paths
    for path in paths - {POPOUT, WIDGET_LAB}:
        assert _directives(sh.csp_for_path(path))["frame-ancestors"] == "'none'", path


def test_the_popout_response_answers_self(client):
    r = client.get(f"{POPOUT}?tab=flow&item=1")
    assert r.status_code == 200, r.status_code
    assert _directives(r.headers["content-security-policy"])["frame-ancestors"] == "'self'"


@pytest.mark.parametrize("path", [
    "/static/index.html",
    "/static/style-guide.html",
    "/static/popout.html/",
    "/static//popout.html",
    "/static/POPOUT.html",
    "/static/dist/widget-lab/index.html/",
    "/static/dist/widget-lab//index.html",
    "/api/v1/browsers/selected",
    "/api/v1/no-such-route",
    "/static/no-such-file.html",
])
def test_every_other_response_answers_none(client, path):
    r = client.get(path)
    assert _directives(r.headers["content-security-policy"])["frame-ancestors"] == "'none'", (path, r.status_code)

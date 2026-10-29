
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_dl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_dl_logs_"))
os.environ.setdefault("CLOUDE_STATE_DIR", tempfile.mkdtemp(prefix="cc_dl_state_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))



def test_deep_link_basic():
    from src.core.notifications import links

    assert links.deep_link("http://mac.lan:8000", "myproject") == "http://mac.lan:8000/session/myproject"


def test_deep_link_strips_trailing_slash():
    from src.core.notifications import links

    assert links.deep_link("http://mac.lan:8000///", "foo") == "http://mac.lan:8000/session/foo"


def test_deep_link_slugifies_dots():
    from src.core.notifications import links

    url = links.deep_link("http://mac.lan:8000", "my.project.v1")
    assert url == "http://mac.lan:8000/session/my_project_v1"
    assert "my.project.v1" not in url


def test_deep_link_returns_none_without_a_base():
    from src.core.notifications import links

    assert links.deep_link("", "anything") is None


def test_deep_link_url_encodes_defensively():
    from src.core.notifications import links

    url = links.deep_link("http://mac.lan:8000", "has space")
    assert " " not in url
    assert url == "http://mac.lan:8000/session/has_space"


def test_session_path_is_the_relative_form_the_web_push_payload_carries():
    from src.core.notifications import links

    assert links.session_path("my.project v1") == "/session/my_project_v1"



def test_slugify_slash_becomes_underscore():
    from src.core.tmux_backend import _slugify

    assert _slugify("foo/bar") == "foo_bar"


def test_slugify_leading_dots_stripped_or_converted():
    from src.core.tmux_backend import _slugify

    assert _slugify("..evil") == "evil"


def test_slugify_handles_path_traversal_attempt():
    from src.core.tmux_backend import _slugify

    out = _slugify("safe..name")
    assert ".." not in out
    assert out == "safe__name"


def test_slugify_empty_input_returns_default():
    from src.core.tmux_backend import _slugify

    assert _slugify("") == "default"
    assert _slugify("...") == "default"



@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from src.main import app

    with TestClient(app) as tc:
        yield tc


def _assert_csp_present(resp):
    csp = resp.headers.get("content-security-policy")
    assert csp is not None, "Content-Security-Policy header missing"
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "connect-src 'self' ws: wss:" in csp
    assert "frame-ancestors 'none'" in csp
    assert "cdn.jsdelivr.net" not in csp, (
        "a third-party origin reappeared in the CSP; vendor the asset instead"
    )
    assert "://" not in csp.replace("ws:", "").replace("wss:", ""), (
        f"CSP names a remote origin: {csp}"
    )
    assert "'unsafe-inline'" in csp.split("style-src")[1].split(";")[0]
    assert "script-src 'self';" in csp
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("referrer-policy") == "no-referrer"


def test_deep_link_route_serves_spa(client):
    resp = client.get("/session/myproject")
    assert resp.status_code == 200
    body = resp.text.lower()
    assert "<!doctype html" in body
    assert "cloude code" in body


def test_deep_link_route_accepts_dotted_name(client):
    resp = client.get("/session/valid_project-1.2.3")
    assert resp.status_code == 200


def test_csp_header_on_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    _assert_csp_present(resp)


def test_csp_header_on_deep_link(client):
    resp = client.get("/session/foo")
    assert resp.status_code == 200
    _assert_csp_present(resp)


def test_csp_header_on_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    _assert_csp_present(resp)


def test_responses_lack_dangerous_headers(client):
    resp = client.get("/session/paranoid")
    assert resp.status_code == 200
    assert "x-powered-by" not in {k.lower() for k in resp.headers.keys()}
    assert "set-cookie" not in {k.lower() for k in resp.headers.keys()}

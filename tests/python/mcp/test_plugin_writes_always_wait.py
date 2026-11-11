
from __future__ import annotations

import os
import tempfile
import time

import jwt
import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.federation import peer_token  # noqa: E402
from src.core.mcp import beast_mode, tools  # noqa: E402
from tests.python.api_keys.conftest import bearer, client  # noqa: E402,F401

PLUGIN_PREFIXES = ("plugin_", "cplug_")


def plugin_writes_missing(table: dict, writes: frozenset) -> list:
    return sorted(n for n in table if n.startswith(PLUGIN_PREFIXES) and n in writes and n not in beast_mode.ALWAYS_WAITS)


def test_every_registered_plugin_write_is_always_wait():
    assert plugin_writes_missing(tools._TOOLS, tools.WRITE_TOOLS) == []
    found = {n for n in tools._TOOLS if n.startswith(PLUGIN_PREFIXES) and n in tools.WRITE_TOOLS}
    assert {"cplug_update", "plugin_sideload_add", "plugin_sideload_remove"} <= found


def test_the_walk_names_a_plugin_write_that_is_not_on_the_list():
    table = dict(tools._TOOLS)
    table["plugin_enable"] = table["cplug_update"]
    assert plugin_writes_missing(table, tools.WRITE_TOOLS | {"plugin_enable"}) == ["plugin_enable"]
    assert "plugin_enable" not in tools._TOOLS


def _peer_bearer() -> dict:
    claims = {"typ": peer_token.PEER_TYP, "sub": "grant", "iat": int(time.time()), "exp": int(time.time()) + 900}
    return bearer(jwt.encode(claims, "not-a-real-key", algorithm="HS256"))


@pytest.mark.parametrize("method,url,body", [
    ("put", "/api/v1/cplugs/huddle", {"revision": 0, "enabled": True}),
    ("post", "/api/v1/cplugs/huddle/restart", {}),
    ("post", "/api/v1/cplugs/huddle/purge", {}),
    ("post", "/api/v1/cplug-owner/sideload", {"path": "/nope"}),
    ("delete", "/api/v1/cplug-owner/sideload?name=x", None),
    ("put", "/api/v1/cplug-owner/sideload/switch", {"enabled": True}),
    ("post", "/api/v1/cplug-owner/sideload/git", {"url": "https://example.invalid/x.git"}),
    ("put", "/api/v1/cplug-owner/switch", {"enabled": True}),
    ("post", "/api/v1/catalog/install", {}),
    ("post", "/api/v1/catalog/installed/x/update", {}),
    ("delete", "/api/v1/catalog/installed/x", None),
    ("patch", "/api/v1/catalog/installed/x", {}),
])
def test_a_peer_token_cannot_install_enable_or_change_a_plugin(client, method, url, body):  # noqa: F811
    kwargs = {"json": body} if body is not None else {}
    r = getattr(client, method)(url, headers=_peer_bearer(), **kwargs)
    assert r.status_code == 403, (method, url, r.status_code, r.text)
    assert r.json()["detail"]["code"] == "peer_forbidden", r.text

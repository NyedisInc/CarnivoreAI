
from __future__ import annotations

import os
import re
import tempfile
from contextlib import closing
from types import SimpleNamespace
from typing import List, Tuple

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_fed_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_fed_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from src.api import peer_auth  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.db import connect, db_path_for, get_meta  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.federation import fed_key, grants, peer_forward, peer_token  # noqa: E402
from src.main import app  # noqa: E402
from tests.test_route_auth_inventory import _dep_calls, _walk  # noqa: E402

PEER_ALLOWED = {
    ("POST", "/api/v1/crosstalk/peer-deliver"): "sessions",
    ("POST", "/api/v1/crosstalk/peer-control"): "sessions",
    ("POST", "/api/v1/crosstalk/peer-spawn"): "sessions",
    ("GET", "/api/v1/sessions/list"): "sessions",
    ("GET", "/api/v1/sessions/asleep"): "sessions",
    ("GET", "/api/v1/sessions/list-and-asleep"): "sessions",
    ("POST", "/api/v1/warroom/screens"): "sessions",
    ("GET", "/api/v1/federation/hello"): "sessions",
    ("POST", "/api/v1/federation/link"): "sessions",
    ("POST", "/api/v1/federation/key/announce"): "sessions",
    ("DELETE", "/api/v1/federation/grants/self"): "sessions",
    ("GET", "/api/v1/projects/history"): "sessions",
    ("GET", "/api/v1/provider-ledger/summary"): "sessions",
    ("GET", "/api/v1/federation/app-update"): "sessions",
    ("PUT", "/api/v1/federation/app-update/auto-update"): "sessions",
    ("POST", "/api/v1/federation/app-update/check"): "sessions",
    ("POST", "/api/v1/federation/app-update/install"): "sessions",
    ("GET", "/api/v1/launchers/summary"): "sessions",
    ("GET", "/api/v1/filesystem/project-folders"): "sessions",
    ("GET", "/api/v1/deepsearch/peer-search"): "sessions",
    ("GET", "/api/v1/deepsearch/peer-context"): "sessions",
    ("GET", "/api/v1/stats/feed/local"): "sessions",
    ("GET", "/api/v1/approvals"): "sessions",
    ("GET", "/api/v1/scheduled-tasks"): "sessions",
    ("POST", "/api/v1/federation/notify-sync/exchange"): "settings",
    ("POST", "/api/v1/federation/notify-sync/secrets"): "settings",
    ("POST", "/api/v1/federation/pack/exchange"): "machine",
    ("GET", "/api/v1/federation/pack/rollup"): "machine",
    ("POST", "/api/v1/federation/link-cert"): "machine",
    ("PUT", "/api/v1/federation/pack/reserve"): "machine",
    ("PUT", "/api/v1/federation/pack/restrictions/tighten"): "machine",
    ("POST", "/api/v1/federation/pack/credentials"): "credentials",
    ("DELETE", "/api/v1/federation/pack/credentials/{account_key}"): "credentials",
    ("POST", "/api/v1/federation/swarm/body"): "replica",
    ("POST", "/api/v1/federation/swarm/body/{home_agent_id}/sleep"): "replica",
    ("POST", "/api/v1/federation/swarm/proxy"): "swarm-proxy",
    ("POST", "/api/v1/federation/swarm/memory/writeback"): "swarm-proxy",
    ("POST", "/api/v1/federation/pack/board/{verb}"): "swarm-proxy",
    ("POST", "/api/v1/federation/pack/refresh"): "refresh",
    ("POST", "/api/v1/federation/pack/replica"): "replica",
    ("DELETE", "/api/v1/federation/pack/replica/{project_uid}"): "replica",
    ("PUT", "/api/v1/federation/pack/blobs/{blob_id}"): "replica",
    ("POST", "/api/v1/federation/pack/blobs/{blob_id}/seal"): "replica",
    ("GET", "/api/v1/federation/pack/blobs/{blob_id}"): "replica",
    ("POST", "/api/v1/federation/pack/bundle/apply"): "replica",
    ("POST", "/api/v1/federation/pack/gh-login"): "credentials",
    ("POST", "/api/v1/federation/pack/skills/offer"): "skills",
    ("POST", "/api/v1/federation/pack/skills/apply"): "skills",
    ("GET", "/api/v1/federation/pack/skills/inventory"): "skills",
    ("PUT", "/api/v1/federation/pack/skills/blobs/{blob_id}"): "skills",
    ("POST", "/api/v1/federation/pack/skills/blobs/{blob_id}/seal"): "skills",
    ("GET", "/api/v1/federation/pack/skills/blobs/{blob_id}"): "skills",
    ("POST", "/api/v1/federation/pack/skills/export"): "skills",
    ("GET", "/api/v1/federation/pack/skills/export/{blob_id}"): "skills",
    ("POST", "/api/v1/federation/pack/skills/export/{blob_id}/done"): "skills",
    **{("POST", f"/api/v1/federation/pack/migrate/{step}"): "migrate" for step in ("prepare", "receive", "verify", "flip", "abort", "back")},
    ("POST", "/api/v1/federation/pack/session/receive"): "migrate",
    ("POST", "/api/v1/federation/pack/carry/check"): "migrate",
    ("POST", "/api/v1/federation/pack/carry/apply"): "migrate",
    **{(r.method, "/api/v1" + r.path): "sessions" for r in peer_forward.TABLE if r.mode in (peer_forward.FORWARD, peer_forward.SELF)},
}

PEER_ALLOWED_SOCKETS = {"/ws/terminal", "/ws/events"}

UNSCOPED_PUBLIC_PREFIXES = ("/api/v1/federation/pair/", "/api/v1/federation/token")


def _routes() -> List[Tuple[str, str, object]]:
    out = []
    for kind, path, route, _inherited in _walk(app.routes):
        if kind == "http":
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                out.append((method, path, route))
    return out


def _peer_scopes(route) -> set:
    return {c.peer_scope for c in _dep_calls(route.dependant) if hasattr(c, "peer_scope")}


def test_only_named_routes_hold_a_peer_dependency() -> None:
    tagged = {(m, p): _peer_scopes(r) for m, p, r in _routes() if _peer_scopes(r)}
    assert tagged == {k: {v} for k, v in PEER_ALLOWED.items()}


def test_only_the_terminal_and_events_sockets_hold_a_peer_dependency() -> None:
    tagged = {p for kind, p, r, _ in _walk(app.routes) if kind != "http" and _peer_scopes(r)}
    assert tagged == PEER_ALLOWED_SOCKETS


def test_the_allow_list_has_no_stale_rows() -> None:
    assert set(PEER_ALLOWED) <= {(m, p) for m, p, _ in _routes()}


@pytest.fixture()
def peer_bearer(tmp_path, monkeypatch) -> str:
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    monkeypatch.setattr(peer_auth, "open_db", lambda: connect(path, create=False))
    with closing(connect(path, create=False)) as conn:
        install_id = get_meta(conn, "install_id")
        pub = fed_key.public_key_b64(fed_key.DeviceKey.from_seed(bytes([9]) * 32))
        grant = grants.create_grant(conn, peer_install_id="iid-peer", public_key=pub, label="peer")
    token, _ = peer_token.mint(grant, install_id)
    return token


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def test_a_peer_token_is_accepted_by_sessions_list_and_hello(peer_bearer, monkeypatch) -> None:
    async def none():
        return None

    monkeypatch.setattr(app.state, "session_manager", SimpleNamespace(get_session_info=none), raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    head = {"Authorization": f"Bearer {peer_bearer}"}
    listing = client.get("/api/v1/sessions/list", headers=head)
    assert listing.status_code == 200, listing.text
    hello = client.get("/api/v1/federation/hello", headers=head)
    assert hello.status_code == 200 and hello.json()["principal"] == "peer"


def test_a_peer_token_gets_401_on_every_unscoped_route(peer_bearer) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    head = {"Authorization": f"Bearer {peer_bearer}"}
    checked = 0
    leaks = []
    for method, path, route in _routes():
        if (method, path) in PEER_ALLOWED or path.startswith(UNSCOPED_PUBLIC_PREFIXES):
            continue
        if not any(c is require_auth or hasattr(c, "peer_scope") for c in _dep_calls(route.dependant)):
            continue
        response = client.request(method, _fill(path), headers=head)
        checked += 1
        if response.status_code != 401:
            leaks.append((method, path, response.status_code))
    assert checked > 100, "the walk saw too few guarded routes to mean anything"
    assert leaks == []


def test_a_peer_token_is_refused_on_every_websocket(peer_bearer) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    for path in ("/ws/browser?browser_id=0123456789abcdef",):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(path, subprotocols=["cloude.jwt.v1", peer_bearer]) as ws:
                ws.receive_text()
        assert exc.value.code == 4401, path


def test_a_revoked_grant_is_refused_at_once_whatever_the_token_life(peer_bearer, tmp_path) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    head = {"Authorization": f"Bearer {peer_bearer}"}
    assert client.get("/api/v1/federation/hello", headers=head).status_code == 200
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        assert grants.revoke(conn, grants.list_grants(conn)[0].grant_id)
    assert client.get("/api/v1/federation/hello", headers=head).status_code == 401

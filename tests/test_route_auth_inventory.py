
from __future__ import annotations

import os
import re
import tempfile
from typing import Iterator, List, Optional, Set, Tuple

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rai_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rai_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi.routing import APIRoute, APIWebSocketRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from src.api.auth import require_auth  # noqa: E402
from src.main import app  # noqa: E402
from src.cplugs.sdk import public_routes  # noqa: E402

PUBLIC_HTTP = {
    ("GET", "/api/v1/cplugs/{cplug_id}/view/{name}/{ticket}/{rest:path}"): "a plugin view frame loads in an iframe, which cannot send a bearer; the signed one-hour ticket in the path is the credential (A15, sidecar_view.py)",
    ("POST", "/api/v1/auth/verify"): "the TOTP login itself",
    ("POST", "/api/v1/auth/refresh"): "exchanges a refresh token, which is its own credential",
    ("POST", "/api/v1/auth/logout"): "revokes the presented refresh token; harmless unauthenticated",
    ("GET", "/api/v1/auth/qr"): "tombstone: always 403 qr_moved, serves nothing",
    ("GET", "/api/v1/auth/enrollment"): "loopback-gated enrollment, section C",
    ("GET", "/api/v1/auth/enrollment/status"): "public paired/local probe",
    ("GET", "/api/v1/auth/join/candidates"): "first-run join: local-transport and unpaired/join_pending gated, #1530 J5c",
    ("POST", "/api/v1/auth/join"): "first-run join: local-transport and unpaired/join_pending gated, #1530 J5c",
    ("GET", "/api/v1/auth/join/status"): "first-run join: local-transport and unpaired/join_pending gated, #1530 J5c",
    ("POST", "/api/v1/auth/join/look"): "first-run look for a pack: same local-transport and unpaired/join_pending gate as /auth/join, opens the Terminal helper, carries no secret, #1622",
    ("GET", "/api/v1/health"): "liveness probe, no data",
    ("GET", "/health"): "liveness probe, no data",
    ("GET", "/api/v1/setup/state"): "first-run wizard: loopback-only while setup is incomplete, require_auth after",
    ("POST", "/api/v1/setup/apply"): "first-run wizard: loopback-only while setup is incomplete, require_auth after",
    ("GET", "/setup"): "first-run wizard page, static shell",
    ("GET", "/"): "the app shell; every datum it shows comes from guarded routes",
    ("GET", "/session/{project}"): "deep-link to the app shell",
    ("GET", "/session"): "redirect to /#sessions, the sessions view; serves no data",
    ("GET", "/layout/{layout_uuid}"): "deep-link to the app shell",
    ("GET", "/archive"): "deep-link to the app shell",
    ("GET", "/archive/{rest:path}"): "deep-link to the app shell",
    ("POST", "/api/v1/federation/pair/begin"): "owner login only (the no-login ssh step is the unix pair socket, never HTTP); gated inside",
    ("POST", "/api/v1/federation/pair/complete"): "the single-use pairing code is the credential; gated inside",
    ("POST", "/api/v1/federation/pair/finish"): "the initiator's accept or cancel, signed with the key it paired with; gated inside (P10)",
    ("POST", "/api/v1/federation/token"): "a signature by a granted Ed25519 key is the credential; gated inside",
    ("POST", "/api/v1/federation/prove"): "signs a caller's own nonce with the federation key; carries no secret",
    ("POST", "/mcp"): "the agent MCP endpoint; the pane's hook token plus its session id is the credential, loopback only, checked by require_agent (issue #152)",
    ("POST", "/api/v1/sessions/{session_id}/agent-message"): "an agent notifies the owner about its OWN session; the pane's hook token is the credential, checked by require_agent, which also refuses another session's path and any external or read token (issue #1278)",
    ("POST", "/api/v1/sessions/{session_id}/messaging/send"): "a bound agent texts the owner as its OWN session; the pane's hook token is the credential, checked by require_agent, which also refuses another session's path and any external or read token (issue #1499)",
    ("POST", "/api/v1/cplugs/huddle/items/{item_id}/wait/resolve"): "the wait callback a script calls when the thing a task waits on is done: the wait's one-time token is the credential, checked and spent atomically (wait_resolve.py, waits.WaitStore.claim_end); every refusal is the same 403 and never says whether the item exists (docs/task-manager.md, Part 1b-2a)",
    ("GET", "/api/v1/cplugs/huddle/artifact-view/{ticket}"): "the huddle artifact viewer: an iframe cannot send a bearer, so a signed one-hour ticket naming one item and one page is the credential (artifact_ticket.py); served under its own sandboxing CSP (docs/task-manager.md section 61)",
    ("GET", "/mcp"): "answers 405 with no data; mcp.enabled false answers 404",
    ("DELETE", "/mcp"): "answers 405 with no data; mcp.enabled false answers 404",
    ("GET", "/manifest.webmanifest"): "add-to-home-screen manifest, static",
    ("GET", "/apple-touch-icon.png"): "home-screen icon, static",
    ("GET", "/sw.js"): "push-only service worker script, static; a browser fetches it with no bearer token and it holds no data",
    ("GET", "/pair"): "phone link pair page; link-only (_require_link), no data, credential is the pairing secret or code",
    ("POST", "/pair/claim"): "phone link claim; link-only (_require_link), the credential is the 256-bit pairing secret",
    ("GET", "/pair/status"): "phone link; link-only (_require_link), answers only whether the caller's own cookies are valid",
    ("POST", "/pair/verify"): "phone link; link-only (_require_link), the credentials are the scan's claim handle cookie AND the authenticator code (the one TOTP check, rate limited)",
    ("POST", "/pair/code"): "phone link claim; link-only (_require_link), the credential is the 8 character pairing code",
}

HANDSHAKE_WS = {"/ws/terminal", "/ws/events", "/ws/browser", "/api/v1/federation/ws"}


def _dep_calls(dependant) -> Iterator[object]:
    for sub in dependant.dependencies:
        yield sub.call
        yield from _dep_calls(sub)


def _walk(routes, prefix: str = "", inherited: Tuple[object, ...] = ()) -> Iterator[Tuple[str, str, object, Tuple[object, ...]]]:
    for route in routes:
        if hasattr(route, "original_router"):
            ctx = route.include_context
            down = inherited + tuple(d.dependency for d in ctx.dependencies or ())
            yield from _walk(route.original_router.routes, prefix + (ctx.prefix or ""), down)
        elif isinstance(route, APIWebSocketRoute):
            yield "ws", prefix + route.path, route, inherited
        elif isinstance(route, APIRoute):
            yield "http", prefix + route.path, route, inherited


def _http_routes() -> List[Tuple[str, str, bool]]:
    out = []
    for kind, path, route, inherited in _walk(app.routes):
        if kind != "http":
            continue
        calls = set(_dep_calls(route.dependant)) | set(inherited)
        guarded = require_auth in calls or any(hasattr(c, "peer_scope") for c in calls)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method, path, guarded))
    return out


def _ws_paths() -> Set[str]:
    return {path for kind, path, _, _ in _walk(app.routes) if kind == "ws"}


def test_the_walk_sees_the_app() -> None:
    routes = _http_routes()
    assert len(routes) > 100
    assert any(guarded for _, _, guarded in routes)
    assert ("GET", "/api/v1/health", False) in routes


def _public_rows() -> dict:
    declared = {(method, f"/api/v1{path}"): why for (method, path), why in public_routes().items()}
    return {**PUBLIC_HTTP, **declared}


def test_every_plugin_declared_public_route_is_really_open() -> None:
    declared = {(m, f"/api/v1{p}") for m, p in public_routes()}
    assert declared <= {(m, p) for m, p, guarded in _http_routes() if not guarded}


def test_add_public_get_records_its_reason_and_a_call_without_one_records_nothing() -> None:
    from fastapi import APIRouter  # noqa: PLC0415

    from src.cplugs.sdk import add_public_get  # noqa: PLC0415

    router = APIRouter(prefix="/cplugs/synthetic")
    add_public_get(router, "synthetic", "/a", lambda: None, "why a is public")
    add_public_get(router, "synthetic", "/b", lambda: None)
    try:
        assert public_routes()[("GET", "/cplugs/synthetic/a")] == "why a is public"
        assert ("GET", "/cplugs/synthetic/b") not in public_routes()
    finally:
        from src.cplugs.sdk import routing  # noqa: PLC0415

        routing._PUBLIC_ROUTES.pop(("GET", "/cplugs/synthetic/a"), None)


def test_every_http_route_is_guarded_or_named_public() -> None:
    open_routes = {(m, p) for m, p, guarded in _http_routes() if not guarded}
    unexplained = sorted(open_routes - set(_public_rows()))
    assert unexplained == [], f"routes with no require_auth and no reason: {unexplained}"


def test_the_public_list_has_no_stale_rows() -> None:
    open_routes = {(m, p) for m, p, guarded in _http_routes() if not guarded}
    stale = sorted(set(_public_rows()) - open_routes)
    assert stale == [], f"PUBLIC_HTTP rows that are not open routes: {stale}"


def test_every_websocket_route_is_a_known_handshake_route() -> None:
    assert _ws_paths() == HANDSHAKE_WS


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


GUARDED = [(m, p) for m, p, guarded in _http_routes() if guarded]


@pytest.mark.parametrize("method,path", GUARDED, ids=[f"{m} {p}" for m, p in GUARDED])
def test_an_unauthenticated_request_is_refused_with_401(method: str, path: str) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.request(method, _fill(path))
    assert response.status_code == 401, (method, path, response.status_code)


def test_a_forged_bearer_is_refused_too() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    forged = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    response = client.get("/api/v1/sessions/list", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


FORGED_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _handshake_close_code(path: str, subprotocols: Optional[List[str]], headers=None) -> int:
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(path, subprotocols=subprotocols, headers=headers or {}) as ws:
            ws.receive_text()
    return exc.value.code


BROWSER_WS = "/ws/browser?browser_id=0123456789abcdef"


@pytest.fixture
def valid_jwt(monkeypatch) -> str:
    from types import SimpleNamespace

    from src.api import auth
    from src.config import settings as real_settings

    fake_auth = SimpleNamespace(
        jwt_secret="test-secret-for-route-auth-inventory", jwt_expiry_minutes=60,
        access_token_ttl_seconds=900, refresh_token_ttl_seconds=604800,
        refresh_grace_seconds=10, totp_secret="X" * 32,
    )

    class _FakeSettings:
        def load_auth_config(self):
            return fake_auth

        def __getattr__(self, name):
            return getattr(real_settings, name)

    monkeypatch.setattr("src.api.auth.settings", _FakeSettings())
    token, _ = auth.create_access_token()
    return token


def test_browser_socket_refuses_a_handshake_with_no_credential() -> None:
    assert _handshake_close_code(BROWSER_WS, None) == 4401


def test_browser_socket_refuses_a_forged_jwt() -> None:
    assert _handshake_close_code(BROWSER_WS, ["cloude.jwt.v1", FORGED_JWT]) == 4401


def test_browser_socket_refuses_a_foreign_origin_even_with_a_valid_jwt(valid_jwt: str) -> None:
    token = valid_jwt
    code = _handshake_close_code(
        BROWSER_WS, ["cloude.jwt.v1", token], headers={"origin": "https://evil.example"}
    )
    from src.api.host_guard import UNTRUSTED_CLOSE_CODE

    assert code == UNTRUSTED_CLOSE_CODE, code


def test_browser_socket_with_a_valid_jwt_reaches_the_id_check(valid_jwt: str, monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(app.state, "browser_manager", SimpleNamespace(state_dir=None), raising=False)
    assert _handshake_close_code("/ws/browser?browser_id=zz", ["cloude.jwt.v1", valid_jwt]) == 4404


@pytest.mark.parametrize("path", sorted(_ws_paths()))
def test_every_websocket_route_refuses_an_unauthenticated_handshake(path: str) -> None:
    assert _handshake_close_code(path, None) == 4401, path

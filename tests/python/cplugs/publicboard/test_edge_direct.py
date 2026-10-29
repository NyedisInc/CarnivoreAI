
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from src.cplugs.publicboard.edge import EdgeConfig, PublicEdge, canonical_ip
from src.cplugs.publicboard.headers import BASE_HEADERS, PERMISSIONS_POLICY, SHELL_CSP, api_headers, frame_headers, shell_headers
from src.cplugs.sdk.sandboxed_html import VIEW_CSP

HOST = b"review.example.test"


def run(edge: PublicEdge, scope: Dict[str, Any]) -> List[Dict[str, Any]]:
    sent: List[Dict[str, Any]] = []

    async def receive() -> Dict[str, Any]:
        return {"type": "websocket.connect"}

    async def send(message: Dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(edge(scope, receive, send))
    return sent


def http_scope(**over: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {"type": "http", "method": "GET", "path": "/api/board", "raw_path": b"/api/board", "query_string": b"",
                            "headers": [(b"host", HOST)], "client": ("203.0.113.11", 5555)}
    return {**base, **over}


@pytest.fixture()
def reached() -> List[str]:
    return []


@pytest.fixture()
def edge(reached: List[str]) -> PublicEdge:
    async def handler(scope: Any, receive: Any, send: Any) -> None:
        reached.append(scope["method"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return PublicEdge(EdgeConfig.of(["203.0.113.11"], ["review.example.test"]), {("GET", "/api/board"): handler})


def status_of(sent: List[Dict[str, Any]]) -> int:
    return int(sent[0]["status"])


def test_a_valid_request_reaches_the_handler_and_only_then(edge: PublicEdge, reached: List[str]) -> None:
    assert status_of(run(edge, http_scope())) == 200 and reached == ["GET"]


@pytest.mark.parametrize("path", ["/", "/api/board", "/ws/events", "/anything"])
def test_a_websocket_scope_is_closed_before_accept_and_never_reaches_a_handler(edge: PublicEdge, reached: List[str], path: str) -> None:
    scope = http_scope(type="websocket", path=path, raw_path=path.encode())
    assert run(edge, scope) == [{"type": "websocket.close", "code": 1008}]
    assert reached == []


def test_a_websocket_from_an_untrusted_peer_is_closed_too(edge: PublicEdge) -> None:
    assert run(edge, http_scope(type="websocket", client=("203.0.113.9", 1))) == [{"type": "websocket.close", "code": 1008}]


def test_an_unknown_scope_type_sends_nothing_and_reaches_nothing(edge: PublicEdge, reached: List[str]) -> None:
    assert run(edge, {"type": "lifespan"}) == [] and reached == []


@pytest.mark.parametrize("client", [None, ("203.0.113.9", 1), ("203.0.113.12", 1), ("203.0.113.110", 1), ("127.0.0.1", 1), ("not-an-ip", 1), ("203.0.113.11%en0", 1), ("", 1)])
def test_only_the_exact_trusted_peer_passes(edge: PublicEdge, reached: List[str], client: Any) -> None:
    assert status_of(run(edge, http_scope(client=client))) == 403 and reached == []


def test_a_mapped_ipv6_spelling_of_the_trusted_peer_is_the_same_peer(edge: PublicEdge) -> None:
    assert status_of(run(edge, http_scope(client=("::ffff:203.0.113.11", 1)))) == 200


def test_the_peer_is_the_socket_never_a_header(edge: PublicEdge, reached: List[str]) -> None:
    spoof = http_scope(client=("203.0.113.9", 1), headers=[(b"host", HOST), (b"x-forwarded-for", b"203.0.113.11")])
    assert status_of(run(edge, spoof)) == 403 and reached == []


def test_a_decoded_path_that_differs_from_the_raw_path_is_judged_on_the_raw_one(edge: PublicEdge, reached: List[str]) -> None:
    sneaky = http_scope(path="/api/board", raw_path=b"/api/%62oard")
    assert status_of(run(edge, sneaky)) == 400 and reached == []


def test_a_missing_raw_path_is_refused(edge: PublicEdge) -> None:
    scope = http_scope()
    del scope["raw_path"]
    assert status_of(run(edge, scope)) == 400


def test_every_refusal_has_the_same_shape(edge: PublicEdge) -> None:
    shapes = {tuple(sorted(run(edge, http_scope(raw_path=b"/nope", path="/nope"))[0]["headers"]))}
    shapes.add(tuple(sorted(run(edge, http_scope(raw_path=b"/Api/board", path="/Api/board"))[0]["headers"])))
    assert len(shapes) == 1


def test_canonical_ip() -> None:
    assert canonical_ip("::ffff:203.0.113.11") == "203.0.113.11" and canonical_ip("203.0.113.011") is None and canonical_ip("evil.example") is None


def test_the_config_refuses_a_proxy_that_is_not_an_ip() -> None:
    with pytest.raises(ValueError):
        EdgeConfig.of(["203.0.113.0/24"], ["a.example.test"])
    with pytest.raises(ValueError):
        EdgeConfig.of(["proxy.example.test"], ["a.example.test"])


def test_the_security_headers_of_every_kind() -> None:
    for kind in (shell_headers(), frame_headers(), api_headers()):
        for name, value in BASE_HEADERS.items():
            assert kind[name] == value
        assert not [h for h in kind if h.lower().startswith("access-control-") or h.lower() == "set-cookie"]
    assert BASE_HEADERS["X-Content-Type-Options"] == "nosniff" and BASE_HEADERS["Referrer-Policy"] == "no-referrer"
    assert BASE_HEADERS["Cross-Origin-Opener-Policy"] == "same-origin" and BASE_HEADERS["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "camera=()" in PERMISSIONS_POLICY and "geolocation=()" in PERMISSIONS_POLICY and "microphone=()" in PERMISSIONS_POLICY
    assert shell_headers()["Content-Security-Policy"] == SHELL_CSP and frame_headers()["Content-Security-Policy"] == VIEW_CSP
    assert frame_headers()["Cache-Control"] == "no-store" and api_headers()["Cache-Control"] == "no-store"


def test_the_shell_csp_is_the_designed_one() -> None:
    assert SHELL_CSP == ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; "
                         "frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
    assert "unsafe-inline" not in SHELL_CSP and "http" not in SHELL_CSP

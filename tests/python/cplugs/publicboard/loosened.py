
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, Optional, Tuple
from unittest import mock

from src.cplugs.publicboard import edge
from src.cplugs.sdk import public_listener


_REAL_TARGET, _REAL_HEADERS = edge.target_refusal, edge.header_refusal


def _decoded_target_refusal(scope: Any) -> Any:
    return _REAL_TARGET({**scope, "raw_path": scope["path"].encode("utf-8")})


def _decoded_route_for(scope: Any, routes: Any) -> Any:
    return routes.get((scope["method"], scope["path"]))


def _prefix_route_for(scope: Any, routes: Any) -> Any:
    for (method, path), handler in routes.items():
        if scope["method"] == method and scope["raw_path"].decode("ascii").startswith(path):
            return handler
    return None


def _casefold_route_for(scope: Any, routes: Any) -> Any:
    return routes.get((scope["method"], scope["raw_path"].decode("ascii").lower()))


def _slash_tolerant_route_for(scope: Any, routes: Any) -> Any:
    return routes.get((scope["method"], scope["raw_path"].decode("ascii").rstrip("/")))


def _no_host_check(scope: Any, config: Any) -> None:
    return None


def _suffix_host_check(scope: Any, config: Any) -> Any:
    values = [v for k, v in scope["headers"] if k == b"host"]
    ok = bool(values) and any(values[0].decode("ascii", "ignore").startswith(name) for name in config.hostnames)
    return None if ok else edge.MISDIRECTED


def _no_peer_check(scope: Any, config: Any) -> None:
    return None


def _xff_peer_check(scope: Any, config: Any) -> Any:
    values = [v.decode("ascii", "ignore") for k, v in scope["headers"] if k == b"x-forwarded-for"]
    peer = values[-1] if values else (scope.get("client") or ("",))[0]
    return None if edge.canonical_ip(peer) in config.trusted_proxies else edge.FORBIDDEN


def _query_allowed(scope: Any) -> Any:
    return _REAL_TARGET({**scope, "query_string": b""})


def _no_dot_check(scope: Any) -> Any:
    raw = scope.get("raw_path")
    if not isinstance(raw, bytes) or len(raw) > edge.MAX_TARGET_BYTES or scope.get("query_string") or not edge.TARGET_CHARS.fullmatch(raw):
        return edge.BAD_REQUEST
    return None


def _long_target_allowed(scope: Any) -> Any:
    with mock.patch.object(edge, "MAX_TARGET_BYTES", 10**6):
        return _REAL_TARGET(scope)


def _no_head_cap(scope: Any) -> None:
    return None


def _no_header_rules(scope: Any) -> None:
    return None


def _content_type_loose(scope: Any) -> Any:
    ctypes = [v for k, v in scope["headers"] if k == b"content-type"]
    if scope["method"] == "POST" and ctypes and ctypes[0].startswith(b"application/json"):
        return None if not [v for k, v in scope["headers"] if k == b"transfer-encoding"] else edge.BAD_REQUEST
    return _REAL_HEADERS(scope)


def _method_override_honoured(scope: Any, routes: Any) -> Any:
    override = [v.decode() for k, v in scope["headers"] if k == b"x-http-method-override"]
    return routes.get((override[0] if override else scope["method"], scope["raw_path"].decode("ascii")))


def _method_not_allowed(send: Any, status: int) -> Any:
    return edge_refuse(send, 405 if status == 404 else status)


edge_refuse = edge.refuse


async def _accept_websocket(self: Any, receive: Any, send: Any) -> None:
    await receive()
    await send({"type": "websocket.accept"})
    await send({"type": "websocket.close", "code": 1000})


@contextmanager
def _patched(*targets: Any) -> Iterator[None]:
    with ExitStack() as stack:
        for obj, name, replacement in targets:
            stack.enter_context(mock.patch.object(obj, name, replacement))
        yield


def _ws_on(app: Any, spec: Any) -> Any:
    config = _REAL_BUILD_CONFIG(app, spec)
    config.ws = "websockets"
    return config


_REAL_BUILD_CONFIG = public_listener.build_config

async def _refuse_without_close(send: Any, status: int) -> None:
    headers = edge.as_asgi(edge.api_headers()) + [(b"content-length", b"0")]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": b""})


def _no_deadline_protocol(spec: Any) -> Any:
    return public_listener.H11Protocol


@dataclass(frozen=True)
class Loosening:

    apply: Callable[[], Any]
    catches: str
    slow: bool = False
    only: Optional[Tuple[str, ...]] = None


LOOSENINGS: Dict[str, Loosening] = {
    "route lookup uses the decoded path": Loosening(lambda: _patched((edge, "route_for", _decoded_route_for), (edge, "target_refusal", _decoded_target_refusal)), "encoding slash-encoded"),
    "route lookup is a prefix match": Loosening(lambda: _patched((edge, "route_for", _prefix_route_for)), "path miss prefix-extension"),
    "route lookup folds case": Loosening(lambda: _patched((edge, "route_for", _casefold_route_for)), "path miss uppercase"),
    "route lookup forgives a trailing slash": Loosening(lambda: _patched((edge, "route_for", _slash_tolerant_route_for)), "path miss trailing-slash"),
    "route lookup honours a method override": Loosening(lambda: _patched((edge, "route_for", _method_override_honoured)), "override X-HTTP-Method-Override: POST on a GET route"),
    "host is not checked": Loosening(lambda: _patched((edge, "host_refusal", _no_host_check)), "host with-port"),
    "host is a prefix match": Loosening(lambda: _patched((edge, "host_refusal", _suffix_host_check)), "host with-port"),
    "peer is not checked": Loosening(lambda: _patched((edge, "peer_refusal", _no_peer_check)), "untrusted peer: perfect GET"),
    "peer comes from x-forwarded-for": Loosening(lambda: _patched((edge, "peer_refusal", _xff_peer_check)), "untrusted peer: spoofed forwarding headers"),
    "query string is ignored": Loosening(lambda: _patched((edge, "target_refusal", _query_allowed)), "path query"),
    "dot segments and doubled slashes pass": Loosening(lambda: _patched((edge, "target_refusal", _no_dot_check)), "path double-slash-prefix"),
    "target length is uncapped": Loosening(lambda: _patched((edge, "target_refusal", _long_target_allowed)), "path too-long"),
    "header block is uncapped": Loosening(lambda: _patched((edge, "head_refusal", _no_head_cap)), "oversized header block"),
    "header rules are skipped": Loosening(lambda: _patched((edge, "header_refusal", _no_header_rules)), "post one byte over the cap"),
    "content type is a prefix match": Loosening(lambda: _patched((edge, "header_refusal", _content_type_loose)), "post content-type with charset"),
    "a miss answers 405": Loosening(lambda: _patched((edge, "refuse", _method_not_allowed)), "path miss uppercase"),
    "a refusal does not close the connection": Loosening(lambda: _patched((edge, "refuse", _refuse_without_close)), "path miss uppercase", only=("path miss uppercase",)),
    "websockets are accepted": Loosening(lambda: _patched((edge.PublicEdge, "_refuse_websocket", _accept_websocket), (public_listener, "build_config", _ws_on)), "websocket upgrade to /"),
    "there is no connection deadline": Loosening(lambda: _patched((public_listener, "deadline_protocol", _no_deadline_protocol)), "slow client is cut at the deadline", slow=True, only=()),
}

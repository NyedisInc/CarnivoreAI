
from __future__ import annotations

from typing import Any, FrozenSet, Tuple

from starlette.routing import BaseRoute, Match, NoMatchFound
from starlette.types import Receive, Scope, Send

from src.core.pack.machines import capabilities

DARK: FrozenSet[Tuple[str, str]] = frozenset({
    ("POST", "/api/v1/federation/pack/mesh/sync"), ("POST", "/api/v1/federation/pack/jobs/look"), ("GET", "/api/v1/pack/removed-logins"),
    ("GET", "/api/v1/pack/rotate"), ("POST", "/api/v1/pack/rotate/start"), ("POST", "/api/v1/pack/rotate/argent"),
    ("PUT", "/api/v1/pack/link-peers"), ("POST", "/api/v1/federation/mesh/token")})
DARK_PATHS: FrozenSet[str] = frozenset(path for _, path in DARK)


def _route_path(scope: Scope) -> str:
    path, root = scope.get("path", ""), scope.get("root_path", "")
    if not root or not path.startswith(root):
        return path
    if path == root:
        return ""
    return path[len(root):] if path[len(root)] == "/" else path


def hidden(scope: Scope) -> bool:
    return scope["type"] == "http" and not capabilities.mesh_on() and _route_path(scope).rstrip("/") in DARK_PATHS


class DarkGate(BaseRoute):

    def matches(self, scope: Scope) -> Tuple[Match, Scope]:
        return (Match.FULL, {}) if hidden(scope) else (Match.NONE, {})

    def url_path_for(self, name: str, /, **path_params: Any) -> Any:
        raise NoMatchFound(name, path_params)

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        await scope["router"].not_found(scope, receive, send)


def install(app: Any) -> None:
    if not any(isinstance(r, DarkGate) for r in app.router.routes):
        app.router.routes.insert(0, DarkGate())

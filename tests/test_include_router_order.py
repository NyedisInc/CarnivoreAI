
from __future__ import annotations

import ast
from pathlib import Path

from fastapi import FastAPI

SRC = Path(__file__).resolve().parent.parent / "src"

REGISTERING_METHODS = frozenset(
    {
        "get", "post", "put", "patch", "delete", "head", "options", "trace",
        "api_route", "websocket", "route", "websocket_route",
        "add_api_route", "add_api_websocket_route", "add_route",
        "add_websocket_route",
    }
)


def late_includes(source: str) -> list[tuple[int, str, int]]:
    tree = ast.parse(source)
    includes: list[tuple[int, str]] = []
    registrations: dict[str, list[int]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        owner = node.func.value
        if method == "include_router":
            if node.args and isinstance(node.args[0], ast.Name):
                includes.append((node.lineno, node.args[0].id))
        elif method in REGISTERING_METHODS and isinstance(owner, ast.Name):
            registrations.setdefault(owner.id, []).append(node.lineno)

    return [
        (line, name, max(registrations[name]))
        for line, name in includes
        if name in registrations and max(registrations[name]) > line
    ]


def test_no_router_in_src_is_included_before_its_handlers():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        for line, name, reg in late_includes(path.read_text()):
            offenders.append(
                f"{path.relative_to(SRC.parent)}:{line}: include_router({name}) "
                f"runs before a {name} route declared on line {reg}"
            )
    assert not offenders, (
        "these includes copy a router before its routes exist, which drops "
        "every later route on FastAPI < 0.141:\n  "
        + "\n  ".join(offenders)
        + "\n\nMove the include below the last handler of that router."
    )


def test_the_detector_flags_the_shape_that_shipped_and_passes_the_fix():
    shipped = (
        "router.include_router(pairing_router)\n"
        "@pairing_router.post('/auth/verify')\n"
        "async def verify(): ...\n"
        "pairing_router.add_api_route('/auth/late', verify)\n"
    )
    fixed = (
        "@pairing_router.post('/auth/verify')\n"
        "async def verify(): ...\n"
        "router.include_router(pairing_router)\n"
        "router.include_router(other_module.router)\n"
    )
    assert late_includes(shipped) == [(1, "pairing_router", 4)]
    assert late_includes(fixed) == []


def test_every_auth_route_is_in_the_assembled_table():
    from src.api.auth_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/auth/verify",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/qr",
        "/api/v1/auth/enrollment",
        "/api/v1/auth/enrollment/status",
        "/api/v1/auth/status",
    }
    assert expected <= paths, f"missing auth routes: {sorted(expected - paths)}"

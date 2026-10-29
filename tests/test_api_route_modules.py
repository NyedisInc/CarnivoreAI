
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

from tests.helpers.guard_fold import assert_no_offenders

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CLOUDE_STATE_DIR", tempfile.mkdtemp(prefix="cc_api_rules_"))
os.environ.setdefault("CLOUDE_TEST_MODE", "1")
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

API = ROOT / "src" / "api"

MAX_LINES = 1000

PRE_EXISTING_OVER_LIMIT: dict[str, int] = {
    "recreate_routes.py": 582,
    "websocket.py": 545,
}

AGGREGATED_ROUTE_FLOOR = 50


def _api_modules() -> list[Path]:
    return sorted(p for p in API.glob("*.py") if p.name != "__init__.py")


def _router_modules() -> list[Path]:
    return [p for p in _api_modules() if "= APIRouter(" in p.read_text()]


def test_the_discovery_finds_something():
    assert len(_api_modules()) >= 30, _api_modules()
    assert len(_router_modules()) >= 25, _router_modules()


def _check_line_guideline(path: Path) -> None:
    count = len(path.read_text().splitlines())
    registered = PRE_EXISTING_OVER_LIMIT.get(path.name)
    if registered is not None:
        assert count <= registered, (
            f"{path.name} is {count} lines, up from the {registered} it was "
            "when it was registered as a pre-existing exception. A file on "
            "that register may shrink or hold; it may not grow."
        )
        return
    assert count <= MAX_LINES, (
        f"{path.relative_to(ROOT)} is {count} lines, over the {MAX_LINES} "
        "guideline. Split it by concern; the flat routes.py reached 4,397 "
        "because nothing ever failed when it grew."
    )


def test_no_route_module_exceeds_the_line_guideline():
    assert_no_offenders("route module line guideline", _api_modules(),
                        _check_line_guideline, label=lambda p: p.name)


def _check_no_aggregator_import(path: Path) -> None:
    tree = ast.parse(path.read_text())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.api.routes":
            offenders.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "src.api":
            offenders.extend(
                node.lineno for a in node.names if a.name == "routes"
            )
        elif isinstance(node, ast.Import):
            offenders.extend(
                node.lineno for a in node.names if a.name == "src.api.routes"
            )
    assert not offenders, (
        f"{path.name} imports the aggregator at line(s) {offenders}. A cycle "
        "resolves fine at runtime, which is why it has to fail here instead."
    )


def test_no_sibling_imports_the_aggregator():
    assert_no_offenders(
        "no sibling imports the aggregator",
        [p for p in _router_modules() if p.name != "routes.py"],
        _check_no_aggregator_import, label=lambda p: p.name,
    )


def _flatten(router) -> list:
    out = []
    for route in getattr(router, "routes", []) or []:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            out.extend(_flatten(inner))
        else:
            out.append(route)
    return out


def _endpoint_names(router) -> set[str]:
    names: set[str] = set()
    for route in _flatten(router):
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None:
            names.add(endpoint.__name__)
    return names


def _application_endpoints() -> set[str]:
    from src.main import app

    return _endpoint_names(app)


def test_the_aggregator_actually_serves_what_it_assembles():
    import src.api.routes as routes

    total = 0

    def count(router) -> None:
        nonlocal total
        for route in router.routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                count(inner)
            else:
                total += 1

    count(routes.router)
    assert total >= AGGREGATED_ROUTE_FLOOR, (
        f"the aggregated router serves {total} routes, fewer than the "
        f"{AGGREGATED_ROUTE_FLOOR} the flat module did. An include_router "
        "line was dropped, and a dropped include is a silent 404 for an "
        "entire resource."
    )


def test_every_router_a_sibling_declares_reaches_the_application():
    import importlib

    served = _application_endpoints()

    def check(path: Path) -> None:
        module = importlib.import_module(f"src.api.{path.stem}")
        declared: set[str] = set()
        for attr in vars(module).values():
            if isinstance(attr, type):
                continue
            if not hasattr(attr, "include_router") or not hasattr(attr, "routes"):
                continue
            declared |= _endpoint_names(attr)
        missing = sorted(declared - served)
        assert not missing, (
            f"{path.name} declares {missing} but the assembled application "
            "serves none of them: an include_router line is missing and those "
            "routes 404 for every caller."
        )

    assert_no_offenders(
        "every declared router reaches the application",
        [p for p in _router_modules() if p.name != "routes.py"],
        check, label=lambda p: p.name,
    )


from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cra_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cra_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import (
    catalog_install_routes,
    catalog_installed_routes,
    catalog_routes,
)

EXPECTED_ROUTES = 11

VALID_BODY = {
    "item_id": "acme/sme",
    "scope": "global",
    "auto_update": True,
    "expected_revision": 1,
}

_PARAMETER = re.compile(r"\{([^}]+)\}")


def _fill(path: str) -> str:
    return _PARAMETER.sub(
        lambda match: "acme/sme" if ":path" in match.group(1) else "i1",
        path,
    )


def route_cases() -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    for router in (
        catalog_routes.router,
        catalog_install_routes.router,
        catalog_installed_routes.router,
    ):
        for route in router.routes:
            path = _fill(route.path)
            for method in route.methods:
                if method in {"HEAD", "OPTIONS"}:
                    continue
                cases.append((method, path))
    return sorted(cases)


def unauthenticated_app() -> FastAPI:
    app = FastAPI()
    app.include_router(catalog_routes.router)
    app.include_router(catalog_install_routes.router)
    app.include_router(catalog_installed_routes.router)
    return app


def test_the_route_list_is_the_one_this_file_was_written_against():
    cases = route_cases()

    assert len(cases) == EXPECTED_ROUTES, cases
    assert ("POST", "/catalog/install") in cases
    assert ("GET", "/catalog/items/acme/sme") in cases
    assert ("DELETE", "/catalog/installed/i1") in cases
    assert ("PATCH", "/catalog/installed/i1") in cases
    assert ("POST", "/catalog/installed/i1/update") in cases


@pytest.mark.parametrize("method,path", route_cases())
def test_no_credentials_is_a_401(method, path):
    with TestClient(unauthenticated_app()) as client:
        response = client.request(method, path, json=VALID_BODY)

    assert response.status_code == 401, response.text
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.parametrize("method,path", route_cases())
def test_a_junk_bearer_token_is_a_401(method, path):
    with TestClient(unauthenticated_app()) as client:
        response = client.request(
            method,
            path,
            json=VALID_BODY,
            headers={"Authorization": "Bearer not.a.real.token"},
        )

    assert response.status_code == 401, response.text
    assert response.headers.get("WWW-Authenticate") == "Bearer"

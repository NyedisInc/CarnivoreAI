
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

KNOWN = Path(__file__).resolve().parents[2] / "fixtures" / "untested_routes_known.json"
API_PREFIX = "/api/v1"
LOOPBACK = "127.0.0.1"


def _known_routes() -> list[str]:
    return json.loads(KNOWN.read_text(encoding="utf-8"))["routes"]


@pytest.fixture(scope="module")
def anonymous_client() -> TestClient:
    from src.config import settings
    from src.main import app

    return TestClient(
        app,
        raise_server_exceptions=False,
        base_url=f"http://{LOOPBACK}:{settings.port}",
        client=(LOOPBACK, 50000),
    )


def test_the_list_is_not_empty_when_there_is_something_to_sweep() -> None:
    assert isinstance(_known_routes(), list)


def _shape(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _mounted_urls(client: TestClient, key: str) -> list[str]:
    method, path = key.split(" ", 1)
    want = _shape(path)
    urls = []
    for full, verbs in client.app.openapi()["paths"].items():
        if method.lower() in verbs and full.startswith(API_PREFIX) and _shape(full).endswith(want):
            urls.append(re.sub(r"\{[^}]*\}", "x", full))
    return urls


@pytest.mark.parametrize("key", _known_routes())
def test_anonymous_request_is_refused(anonymous_client: TestClient, key: str) -> None:
    urls = _mounted_urls(anonymous_client, key)
    assert urls, f"{key} is not served by the core app: remove it from the list or give it its own test"
    method = key.split(" ", 1)[0]
    for url in urls:
        resp = anonymous_client.request(method, url, json={} if method != "GET" else None)
        assert resp.status_code == 401, f"{key} at {url} answered {resp.status_code} to an anonymous caller"

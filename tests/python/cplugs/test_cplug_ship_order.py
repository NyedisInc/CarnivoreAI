
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs import registry
from src.cplugs.host import routes as host_routes, runtime

ROOT = Path(__file__).resolve().parents[3]
ORDER_FILE = ROOT / "src/cplugs/order.json"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    host = runtime.install(app, tmp_path)
    host.publish = lambda topic: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def test_the_listing_carries_no_unread_order_copy(client: TestClient) -> None:
    assert set(client.get("/api/v1/cplugs").json()) == {"cplugs"}


def test_the_registry_sorts_by_the_file_and_has_no_literal_copy() -> None:
    names = json.loads(ORDER_FILE.read_text())["order"]
    present = [n for n in names if (ROOT / "src/cplugs" / n / "cplug.json").is_file()]
    assert registry.plugin_folders()[: len(present)] == present
    assert "huddle\", \"unread\"" not in (ROOT / "src/cplugs/registry.py").read_text()

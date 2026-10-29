
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.layouts_helpers import migrated  # noqa: F401

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.hosts_routes import router as hosts_router
from src.core.db import db_path_for

API = "/api/v1/hosts"


@pytest.fixture
def setup(tmp_path: Path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    migrated(state_dir)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    conn = sqlite3.connect(db_path_for(state_dir))
    conn.execute("INSERT INTO pack_machines (install_id, label, is_self, updated_at) VALUES ('iid-hosta', 'hosta', 0, 1.0)")
    conn.commit()
    conn.close()
    app = FastAPI()
    app.include_router(hosts_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    client = TestClient(app)
    key = client.post(API, json={"label": "Hosta", "ssh_target": "acme@hosta"}).json()["key"]
    return client, key


def test_link_persists_and_get_hosts_reports_it(setup) -> None:
    client, key = setup
    res = client.put(f"{API}/{key}/computer", json={"computer_install_id": "iid-hosta"})
    assert res.status_code == 200 and res.json()["computer_install_id"] == "iid-hosta"
    listed = {h["key"]: h for h in client.get(API).json()["hosts"]}
    assert listed[key]["computer_install_id"] == "iid-hosta"
    assert listed["local"]["computer_install_id"] is None


def test_null_clears_the_link(setup) -> None:
    client, key = setup
    client.put(f"{API}/{key}/computer", json={"computer_install_id": "iid-hosta"})
    res = client.put(f"{API}/{key}/computer", json={"computer_install_id": None})
    assert res.status_code == 200 and res.json()["computer_install_id"] is None


def test_unknown_computer_host_and_local_are_refused(setup) -> None:
    client, key = setup
    bad = client.put(f"{API}/{key}/computer", json={"computer_install_id": "nope"})
    assert bad.status_code == 404 and bad.json()["detail"]["code"] == "computer_not_found"
    assert client.put(f"{API}/ghost/computer", json={"computer_install_id": "iid-hosta"}).status_code == 404
    local = client.put(f"{API}/local/computer", json={"computer_install_id": "iid-hosta"})
    assert local.status_code == 409 and local.json()["detail"]["code"] == "host_local_fixed"

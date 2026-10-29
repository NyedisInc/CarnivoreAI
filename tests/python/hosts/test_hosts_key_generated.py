
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator
from unittest import mock

import pytest

from tests.layouts_helpers import migrated  # noqa: F401

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.hosts_routes import router as hosts_router
from src.core.hosts import store

API = "/api/v1/hosts"
KEY_RE = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    from src.config import settings

    state_dir = tmp_path / "state"
    migrated(state_dir)
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    app = FastAPI()
    app.include_router(hosts_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return TestClient(app)


def test_a_body_carrying_key_is_refused(client: TestClient) -> None:
    res = client.post(API, json={"key": "studio", "label": "Studio", "ssh_target": "studio"})
    assert res.status_code == 422


def test_the_generated_key_is_32_lowercase_hex_characters(client: TestClient) -> None:
    res = client.post(API, json={"label": "Studio", "ssh_target": "studio"})
    assert res.status_code == 200
    assert KEY_RE.fullmatch(res.json()["key"])


def test_two_adds_get_distinct_keys(client: TestClient) -> None:
    first = client.post(API, json={"label": "Studio", "ssh_target": "studio"}).json()["key"]
    second = client.post(API, json={"label": "Studio", "ssh_target": "studio"}).json()["key"]
    assert first != second


def test_probe_patch_and_delete_all_work_by_the_returned_key(client: TestClient) -> None:
    key = client.post(API, json={"label": "Studio", "ssh_target": "studio"}).json()["key"]

    probed = client.post(f"{API}/{key}/probe")
    assert probed.status_code == 200
    assert probed.json()["key"] == key

    patched = client.patch(f"{API}/{key}", json={"label": "Studio (studio)"})
    assert patched.status_code == 200 and patched.json()["label"] == "Studio (studio)"

    deleted = client.delete(f"{API}/{key}")
    assert deleted.status_code == 200 and deleted.json() == {"key": key, "deleted": True}

    assert client.get(f"{API}/{key}").status_code == 404


def test_the_practically_impossible_collision_retries_instead_of_overwriting(tmp_path: Path) -> None:
    from contextlib import closing

    from src.core.db import connect

    db_path = migrated(tmp_path / "state")
    with closing(connect(db_path, create=False)) as conn:
        with mock.patch.object(store, "generate_key", return_value="dupe"):
            first = store.create_host(conn, label="Studio", ssh_target="studio")
        assert first.key == "dupe"
        calls = iter(["dupe", "fresh"])
        with mock.patch.object(store, "generate_key", side_effect=lambda: next(calls)):
            second = store.create_host(conn, label="Studio", ssh_target="studio")
        assert second.key == "fresh"
        assert store.get_host(conn, "dupe").label == "Studio"


def test_key_generation_gives_up_after_exhausting_its_retries(tmp_path: Path) -> None:
    from contextlib import closing

    from src.core.db import connect

    db_path = migrated(tmp_path / "state")
    with closing(connect(db_path, create=False)) as conn:
        made = store.create_host(conn, label="Studio", ssh_target="studio")
        with mock.patch.object(store, "generate_key", return_value=made.key):
            with pytest.raises(store.HostKeyTaken):
                store.create_host(conn, label="Studio", ssh_target="studio")

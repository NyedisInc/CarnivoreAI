
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sgp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sgp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.session_groups_routes import router as groups_router
from src.core import session_group_store as store
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.session_groups.session_group_parent import GroupParentInvalid


@pytest.fixture()
def conn(tmp_path: Path):
    ensure_db_migrated(tmp_path)
    c = connect(db_path_for(tmp_path))
    yield c
    c.close()


def test_create_nested_groups_across_containers_and_group_chain(conn):
    top = store.create_group(conn, "Top")
    in_pinned = store.create_group(conn, "Active", parent_key="pinned")
    in_layouts = store.create_group(conn, "Workspaces", parent_key="layouts")
    in_layout = store.create_group(conn, "LayoutLive", parent_key="layout:lay-1")
    in_company = store.create_group(conn, "CV", parent_key="c:7")
    in_project = store.create_group(conn, "Live", parent_key="p:42")
    in_group = store.create_group(conn, "Deep", parent_key=f"g:{in_company.group_uuid}")

    by_id = {g.group_uuid: g for g in store.list_groups(conn)}
    assert by_id[top.group_uuid].parent_key is None
    assert by_id[in_pinned.group_uuid].parent_key == "pinned"
    assert by_id[in_layouts.group_uuid].parent_key == "layouts"
    assert by_id[in_layout.group_uuid].parent_key == "layout:lay-1"
    assert by_id[in_company.group_uuid].parent_key == "c:7"
    assert by_id[in_project.group_uuid].parent_key == "p:42"
    assert by_id[in_group.group_uuid].parent_key == f"g:{in_company.group_uuid}"


def test_parent_key_validation_and_cycle_rejection(conn):
    a = store.create_group(conn, "A")
    b = store.create_group(conn, "B", parent_key=f"g:{a.group_uuid}")
    with pytest.raises(GroupParentInvalid):
        store.create_group(conn, "Bad", parent_key="nope:1")
    with pytest.raises(store.GroupNotFound):
        store.create_group(conn, "Missing", parent_key="g:does-not-exist")
    with pytest.raises(GroupParentInvalid):
        store.set_group_parent(conn, a.group_uuid, f"g:{a.group_uuid}")
    with pytest.raises(GroupParentInvalid):
        store.set_group_parent(conn, a.group_uuid, f"g:{b.group_uuid}")


def test_deleting_parent_group_promotes_children_to_grandparent(conn):
    parent = store.create_group(conn, "Parent", parent_key="c:9")
    child = store.create_group(conn, "Child", parent_key=f"g:{parent.group_uuid}")

    store.delete_group(conn, parent.group_uuid)
    remaining = {g.group_uuid: g for g in store.list_groups(conn)}
    assert parent.group_uuid not in remaining
    assert remaining[child.group_uuid].parent_key == "c:9"


def test_http_create_and_reparent_nested_group(tmp_path: Path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state_dir, raising=True)
    assert ensure_db_migrated(state_dir).status == "ok"

    app = FastAPI()
    app.include_router(groups_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        r = client.post("/api/v1/session-groups", json={"name": "Active", "parent_key": "pinned"})
        assert r.status_code == 200
        g = r.json()["groups"][0]
        assert g["parent_key"] == "pinned"

        r2 = client.patch(f"/api/v1/session-groups/{g['group_uuid']}", json={"parent_key": "c:12"})
        assert r2.status_code == 200
        assert r2.json()["groups"][0]["parent_key"] == "c:12"
        assert r2.json()["groups"][0]["name"] == "Active"

        r3 = client.patch(f"/api/v1/session-groups/{g['group_uuid']}", json={"parent_key": None})
        assert r3.status_code == 200
        assert r3.json()["groups"][0]["parent_key"] is None

        bad = client.post("/api/v1/session-groups", json={"name": "X", "parent_key": "invalid"})
        assert bad.status_code == 400

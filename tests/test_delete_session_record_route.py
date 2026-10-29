
from __future__ import annotations

import pytest

from src.core import session_store
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import SESSION_LIFECYCLE_STOPPED
from tests.lifecycle_helpers import add_row


def _settings():
    from src.api.session_records_routes import settings

    return settings


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router as sessions_router

    app = FastAPI()
    app.include_router(sessions_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


@pytest.fixture()
def seeded(monkeypatch, tmp_path):
    monkeypatch.setattr(type(_settings()), "get_state_dir", lambda self: tmp_path)
    ensure_db_migrated(tmp_path, 4, "test")
    conn = connect(db_path_for(tmp_path), create=True)
    try:
        add_row(
            conn,
            uuid="target",
            name="cloude_target",
            epoch=9000,
            lifecycle=SESSION_LIFECYCLE_STOPPED,
        )
        conn.commit()
    finally:
        conn.close()
    return tmp_path


def _archived_at(state_dir, uuid):
    conn = connect(db_path_for(state_dir), create=False)
    try:
        row = conn.execute(
            "SELECT archived_at FROM sessions WHERE session_uuid = ?", (uuid,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "the row was REMOVED - this must be a soft delete"
    return row["archived_at"]


def test_delete_hides_the_row_and_keeps_it(seeded):
    resp = _client().request("DELETE", "/api/v1/sessions/records/target")
    assert resp.status_code == 200
    assert "kept" in resp.json()["message"]

    assert _archived_at(seeded, "target"), "archived_at must be stamped"

    conn = connect(db_path_for(seeded), create=False)
    try:
        listed = {r["session_uuid"] for r in session_store.listable_sessions(conn)}
    finally:
        conn.close()
    assert "target" not in listed


def test_delete_twice_is_reported_as_already_deleted(seeded):
    client = _client()
    first = client.request("DELETE", "/api/v1/sessions/records/target")
    stamp = _archived_at(seeded, "target")
    second = client.request("DELETE", "/api/v1/sessions/records/target")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "already" in second.json()["message"].lower()
    assert _archived_at(seeded, "target") == stamp, "the first stamp must win"


def test_delete_of_an_unknown_uuid_is_404_not_a_silent_success(seeded):
    client = _client()
    assert client.request(
        "DELETE", "/api/v1/sessions/records/target"
    ).status_code == 200, "control failed: the route is not answering at all"

    resp = client.request("DELETE", "/api/v1/sessions/records/no-such-uuid")
    assert resp.status_code == 404


def test_delete_with_no_datastore_is_503_not_200(monkeypatch, tmp_path):
    monkeypatch.setattr(type(_settings()), "get_state_dir", lambda self: tmp_path)
    resp = _client().request("DELETE", "/api/v1/sessions/records/target")
    assert resp.status_code == 503


def test_delete_does_not_reach_the_kill_path(seeded, monkeypatch):
    import shutil

    def _explode(*args, **kwargs):
        raise AssertionError("the delete route must not remove files")

    monkeypatch.setattr(shutil, "rmtree", _explode)
    resp = _client().request("DELETE", "/api/v1/sessions/records/target")
    assert resp.status_code == 200


def test_a_deleted_row_still_carries_its_identity_for_the_reconciler(seeded):
    _client().request("DELETE", "/api/v1/sessions/records/target")
    conn = connect(db_path_for(seeded), create=False)
    try:
        row = conn.execute(
            "SELECT tmux_name, tmux_created_epoch, tmux_socket FROM sessions "
            "WHERE session_uuid = ?",
            ("target",),
        ).fetchone()
    finally:
        conn.close()
    assert row["tmux_name"] == "cloude_target"
    assert row["tmux_created_epoch"] == 9000
    assert row["tmux_socket"]




def test_unarchive_restores_an_archived_row(seeded):
    client = _client()
    client.request("DELETE", "/api/v1/sessions/records/target")
    assert _archived_at(seeded, "target"), "control failed: row not archived"

    resp = client.post("/api/v1/sessions/records/target/unarchive")
    assert resp.status_code == 200
    assert "restored" in resp.json()["message"].lower()
    assert _archived_at(seeded, "target") is None

    conn = connect(db_path_for(seeded), create=False)
    try:
        listed = {r["session_uuid"] for r in session_store.listable_sessions(conn)}
    finally:
        conn.close()
    assert "target" in listed


def test_unarchive_of_a_live_row_is_200_not_an_error(seeded):
    resp = _client().post("/api/v1/sessions/records/target/unarchive")
    assert resp.status_code == 200
    assert "already" in resp.json()["message"].lower()
    assert _archived_at(seeded, "target") is None


def test_unarchive_of_an_unknown_uuid_is_404(seeded):
    client = _client()
    assert client.request(
        "DELETE", "/api/v1/sessions/records/target"
    ).status_code == 200, "control failed: the route is not answering at all"

    resp = client.post("/api/v1/sessions/records/no-such-uuid/unarchive")
    assert resp.status_code == 404


def test_unarchive_with_no_datastore_is_503_not_200(monkeypatch, tmp_path):
    monkeypatch.setattr(type(_settings()), "get_state_dir", lambda self: tmp_path)
    resp = _client().post("/api/v1/sessions/records/target/unarchive")
    assert resp.status_code == 503

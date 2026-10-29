
from __future__ import annotations

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import SESSION_LIFECYCLE_STOPPED
from tests.lifecycle_helpers import add_row


def _client(*, authed: bool):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router as sessions_router

    app = FastAPI()
    app.include_router(sessions_router, prefix="/api/v1")
    if authed:
        app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


@pytest.fixture()
def seeded(monkeypatch, tmp_path):
    from src.api.session_records_routes import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path)
    ensure_db_migrated(tmp_path, 4, "test")
    conn = connect(db_path_for(tmp_path), create=True)
    try:
        add_row(conn, uuid="live", name="carnivore_live", epoch=9000)
        add_row(conn, uuid="old", name="carnivore_old", epoch=8000,
                lifecycle=SESSION_LIFECYCLE_STOPPED, archived_at="2026-10-01T00:00:00")
        add_row(conn, uuid="imported", name=None, epoch=7000,
                lifecycle=SESSION_LIFECYCLE_STOPPED, archived_at="2026-10-02T00:00:00")
        add_row(conn, uuid="closed", name="carnivore_closed", epoch=6000,
                lifecycle=SESSION_LIFECYCLE_STOPPED)
        conn.commit()
    finally:
        conn.close()
    return tmp_path


def test_archived_only_returns_the_archived_rows_alone(seeded):
    client = _client(authed=True)
    every = client.get("/api/v1/sessions/records")
    assert every.status_code == 200
    assert {r["session_uuid"] for r in every.json()} == {"live", "old", "imported", "closed"}
    only = client.get("/api/v1/sessions/records", params={"archived_only": "true"})
    assert only.status_code == 200
    rows = only.json()
    assert {r["session_uuid"] for r in rows} == {"old", "imported"}
    assert all(r["archived_at"] for r in rows)
    by_uuid = {r["session_uuid"]: r for r in every.json()}
    assert by_uuid["closed"]["closed"] is True and by_uuid["closed"]["asleep"] is False
    assert by_uuid["live"]["closed"] is False and by_uuid["old"]["closed"] is False


def test_archived_only_is_behind_auth(seeded):
    response = _client(authed=False).get("/api/v1/sessions/records", params={"archived_only": "true"})
    assert response.status_code == 401

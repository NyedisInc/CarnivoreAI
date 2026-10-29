from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import SESSION_LIFECYCLE_STOPPED
from tests.lifecycle_helpers import add_row


@pytest.fixture()
def state(monkeypatch, tmp_path: Path) -> Path:
    from src.api.library_cleanup_routes import settings
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path)
    ensure_db_migrated(tmp_path, 4, "test")
    return tmp_path


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.library_cleanup_routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    return TestClient(app)


def test_session_delete_is_soft_and_only_purge_removes_the_row(state: Path):
    with closing(connect(db_path_for(state), create=False)) as conn:
        add_row(conn, uuid="lone-row", name="cloude_lone", epoch=1, lifecycle=SESSION_LIFECYCLE_STOPPED)
        conn.commit()
    client = _client()
    soft = client.delete("/api/v1/library/sessions/lone-row")
    assert soft.status_code == 200 and soft.json()["mode"] == "soft"
    with closing(connect(db_path_for(state), create=False)) as conn:
        row = conn.execute("SELECT archived_at FROM sessions WHERE session_uuid = 'lone-row'").fetchone()
    assert row is not None and row[0], "the soft delete keeps the row, stamped archived"
    assert client.delete("/api/v1/library/sessions/lone-row?purge=true").json()["mode"] == "purge"
    with closing(connect(db_path_for(state), create=False)) as conn:
        assert conn.execute("SELECT 1 FROM sessions WHERE session_uuid = 'lone-row'").fetchone() is None
    assert client.delete("/api/v1/library/sessions/lone-row").status_code == 404

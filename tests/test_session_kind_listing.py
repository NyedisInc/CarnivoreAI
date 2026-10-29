
from __future__ import annotations

from contextlib import closing
from pathlib import Path

import pytest

from src.core import session_store
from src.core.db import column_exists, connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    CURRENT_SCHEMA_VERSION,
    SESSION_LIFECYCLE_STOPPED,
)
from src.core.session_kind import (
    KIND_AUTOMATED,
    KIND_INTERACTIVE,
    KIND_UNKNOWN,
)
from tests.lifecycle_helpers import add_row

ROOT = Path(__file__).resolve().parents[1]


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


def _set_kind(conn, uuid, kind):
    conn.execute(
        "UPDATE sessions SET kind = ? WHERE session_uuid = ?", (kind, uuid)
    )


@pytest.fixture()
def conn(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection


@pytest.fixture()
def seeded(monkeypatch, tmp_path):
    monkeypatch.setattr(type(_settings()), "get_state_dir", lambda self: tmp_path)
    ensure_db_migrated(tmp_path, 4, "test")
    connection = connect(db_path_for(tmp_path), create=True)
    try:
        for index, (uuid, kind) in enumerate(
            (
                ("bot", KIND_AUTOMATED),
                ("mine", KIND_INTERACTIVE),
                ("dunno", KIND_UNKNOWN),
                ("never", None),
            )
        ):
            add_row(
                connection,
                uuid=uuid,
                name=f"cloude_{uuid}",
                epoch=7000 + index,
                lifecycle=SESSION_LIFECYCLE_STOPPED,
            )
            _set_kind(connection, uuid, kind)
        connection.commit()
    finally:
        connection.close()
    return tmp_path


def _uuids(rows):
    return {str(row["session_uuid"]) for row in rows}




def test_v25_adds_the_kind_column(conn):
    assert CURRENT_SCHEMA_VERSION >= 25
    assert column_exists(conn, "sessions", "kind")


def test_v25_stamps_rows_this_app_made_and_leaves_imported_null(tmp_path):
    ensure_db_migrated(tmp_path, 4, "test")
    with closing(connect(db_path_for(tmp_path))) as connection:
        for index, origin in enumerate(("created", "adopted", "imported")):
            add_row(
                connection,
                uuid=origin,
                name=f"cloude_{origin}",
                epoch=8100 + index,
                origin=origin,
            )
        connection.commit()
        from src.core.db_models import DDL_V25_SESSIONS_KIND_BACKFILL

        connection.execute(DDL_V25_SESSIONS_KIND_BACKFILL)
        kinds = dict(
            connection.execute("SELECT session_uuid, kind FROM sessions")
        )
    assert kinds["created"] == KIND_INTERACTIVE
    assert kinds["adopted"] == KIND_INTERACTIVE
    assert kinds["imported"] is None, (
        "an imported row must stay NULL - stamping it would destroy the "
        "only thing separating 'classified' from 'never looked at'"
    )


def test_the_v25_backfill_never_overwrites_a_decided_kind(tmp_path):
    from src.core.db_models import DDL_V25_SESSIONS_KIND_BACKFILL

    ensure_db_migrated(tmp_path, 4, "test")
    with closing(connect(db_path_for(tmp_path))) as connection:
        add_row(connection, uuid="c", name="cloude_c", epoch=8200, origin="created")
        _set_kind(connection, "c", KIND_AUTOMATED)
        connection.execute(DDL_V25_SESSIONS_KIND_BACKFILL)
        connection.execute(DDL_V25_SESSIONS_KIND_BACKFILL)
        row = connection.execute(
            "SELECT kind FROM sessions WHERE session_uuid = 'c'"
        ).fetchone()
    assert row["kind"] == KIND_AUTOMATED




def test_list_sessions_still_returns_everything_by_default(conn):
    add_row(conn, uuid="bot", name="cloude_bot", epoch=8300)
    _set_kind(conn, "bot", KIND_AUTOMATED)
    assert "bot" in _uuids(session_store.list_sessions(conn))


def test_listable_sessions_drops_automated_and_keeps_the_rest(conn):
    for index, (uuid, kind) in enumerate(
        (
            ("bot", KIND_AUTOMATED),
            ("mine", KIND_INTERACTIVE),
            ("dunno", KIND_UNKNOWN),
            ("never", None),
        )
    ):
        add_row(conn, uuid=uuid, name=f"cloude_{uuid}", epoch=8400 + index)
        _set_kind(conn, uuid, kind)
    listed = _uuids(session_store.listable_sessions(conn))
    assert "bot" not in listed
    assert {"mine", "dunno", "never"} <= listed, (
        "NULL and 'unknown' must survive: not having looked is not "
        "evidence of automation"
    )




def test_records_route_hides_automated_by_default(seeded):
    resp = _client().get("/api/v1/sessions/records")
    assert resp.status_code == 200
    listed = _uuids(resp.json())
    assert "bot" not in listed
    assert {"mine", "dunno", "never"} <= listed


def test_records_route_returns_automated_when_asked(seeded):
    resp = _client().get("/api/v1/sessions/records?include_automated=true")
    assert resp.status_code == 200
    assert "bot" in _uuids(resp.json())


def _recent(client, query=""):
    from types import SimpleNamespace

    class _Manager:
        pass

    client.app.state.session_manager = _Manager()
    client.app.state.services = SimpleNamespace(
        probe_health=SimpleNamespace(
            health=SimpleNamespace(ok=True, reason=None)
        )
    )
    resp = client.get(f"/api/v1/sessions/recent{query}")
    assert resp.status_code == 200
    return resp.json()


def test_recent_hides_automated_by_default(seeded):
    body = _recent(_client(), "?include_archived=true")
    listed = {row["session_uuid"] for row in body["sessions"]}
    assert "bot" not in listed
    assert {"mine", "dunno", "never"} <= listed


def test_recent_returns_automated_when_asked(seeded):
    body = _recent(
        _client(), "?include_archived=true&include_automated=true"
    )
    assert "bot" in {row["session_uuid"] for row in body["sessions"]}

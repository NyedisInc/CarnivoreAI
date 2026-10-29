
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_note_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_note_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from contextlib import closing

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.api.session_notes_routes import router as notes_router
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.event_hub import EventHub
from src.core.session_notes_store import NOTE_MAX_BYTES

NAME = "cloude_notes_a"
PATH = f"/api/v1/sessions/{NAME}/note"


class RecordingHub(EventHub):

    def __init__(self) -> None:
        super().__init__()
        self.frames: list = []

    def publish(self, frame):  # type: ignore[override]
        self.frames.append(frame)
        return super().publish(frame)


def _store_session(state_dir, name: str) -> str:
    session_uuid = f"uuid-{name}"
    with closing(connect(db_path_for(state_dir))) as conn:
        with conn:
            conn.execute(
                "INSERT INTO sessions "
                "(session_uuid, tmux_socket, tmux_name, tmux_created_epoch, "
                " origin, lifecycle, created_at, updated_at) "
                "VALUES (?, 'cloude', ?, 1, 'created', 'running', "
                "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                (session_uuid, name),
            )
    return session_uuid


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(
        type(settings), "get_state_dir", lambda self: state_dir, raising=True
    )
    assert ensure_db_migrated(state_dir).status == "ok"
    _store_session(state_dir, NAME)

    app = FastAPI()
    app.include_router(notes_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    hub = RecordingHub()
    app.state.event_hub = hub
    with TestClient(app) as client:
        yield client, state_dir, hub




def test_an_absent_note_reads_as_empty_at_revision_zero(app_env) -> None:
    client, _state, _hub = app_env
    response = client.get(PATH)
    assert response.status_code == 200
    body = response.json()
    assert body["body"] == ""
    assert body["revision"] == 0
    assert body["updated_at"] is None


def test_a_name_with_no_stored_session_is_a_404(app_env) -> None:
    client, state, _hub = app_env
    assert client.get("/api/v1/sessions/cloude_no_such/note").status_code == 404
    with closing(connect(db_path_for(state))) as conn:
        assert conn.execute("SELECT COUNT(*) FROM session_notes").fetchone()[0] == 0


def test_the_path_takes_the_TMUX_NAME_and_not_the_storage_key(app_env) -> None:
    client, _state, _hub = app_env
    stored_uuid = f"uuid-{NAME}"

    assert client.get(PATH).status_code == 200
    assert client.get(f"/api/v1/sessions/{stored_uuid}/note").status_code == 404
    assert client.put(
        f"/api/v1/sessions/{stored_uuid}/note",
        json={"body": "wrong handle", "expected_revision": 0},
    ).status_code == 404


def test_a_404_write_creates_nothing(app_env) -> None:
    client, state, _hub = app_env
    refused = client.put(
        "/api/v1/sessions/cloude_no_such/note",
        json={"body": "orphan", "expected_revision": 0},
    )
    assert refused.status_code == 404
    with closing(connect(db_path_for(state))) as conn:
        assert conn.execute("SELECT COUNT(*) FROM session_notes").fetchone()[0] == 0




def test_the_first_write_commits_at_revision_one_and_round_trips(app_env) -> None:
    client, _state, _hub = app_env
    written = client.put(
        PATH, json={"body": "# todo\n\n- check the pipe reader\n", "expected_revision": 0}
    )
    assert written.status_code == 200
    assert written.json()["status"] == "committed"
    assert written.json()["revision"] == 1

    read = client.get(PATH).json()
    assert read["body"] == "# todo\n\n- check the pipe reader\n"
    assert read["revision"] == 1
    assert read["updated_at"]


def test_a_stale_write_is_a_409_carrying_the_current_note(app_env) -> None:
    client, _state, _hub = app_env
    client.put(PATH, json={"body": "mine", "expected_revision": 0})

    refused = client.put(PATH, json={"body": "clobber", "expected_revision": 0})

    assert refused.status_code == 409
    payload = refused.json()["detail"]
    assert payload["status"] == "stale_revision"
    assert payload["revision"] == 1
    assert payload["body"] == "mine"
    assert payload["detail"]
    assert client.get(PATH).json()["body"] == "mine"


def test_without_the_check_the_same_write_would_have_landed(app_env) -> None:
    client, _state, _hub = app_env
    client.put(PATH, json={"body": "mine", "expected_revision": 0})
    landed = client.put(PATH, json={"body": "clobber", "expected_revision": 1})
    assert landed.status_code == 200
    assert landed.json()["revision"] == 2
    assert client.get(PATH).json()["body"] == "clobber"


def test_a_note_over_the_cap_is_a_413_naming_the_limit(app_env) -> None:
    client, _state, _hub = app_env
    over = client.put(
        PATH, json={"body": "x" * (NOTE_MAX_BYTES + 1), "expected_revision": 0}
    )
    assert over.status_code == 413
    assert "256" in over.json()["detail"]["detail"]
    assert client.get(PATH).json()["body"] == ""


def test_an_unchanged_body_moves_no_revision(app_env) -> None:
    client, _state, _hub = app_env
    client.put(PATH, json={"body": "same", "expected_revision": 0})
    again = client.put(PATH, json={"body": "same", "expected_revision": 1})
    assert again.status_code == 200
    assert again.json()["status"] == "unchanged"
    assert again.json()["revision"] == 1


def test_a_write_with_no_expected_revision_is_refused_as_malformed(app_env) -> None:
    client, _state, _hub = app_env
    assert client.put(PATH, json={"body": "x"}).status_code == 422




def test_a_commit_publishes_one_frame_carrying_no_note_text(app_env) -> None:
    client, _state, hub = app_env
    client.put(PATH, json={"body": "secret words", "expected_revision": 0})

    assert len(hub.frames) == 1
    frame = hub.frames[0]
    assert frame["type"] == "session.note.changed"
    assert frame["tmux_session"] == NAME
    assert frame["session_uuid"] == f"uuid-{NAME}"
    assert frame["revision"] == 1
    assert "secret words" not in repr(frame)
    assert "body" not in frame


def test_a_refused_or_unchanged_write_publishes_nothing(app_env) -> None:
    client, _state, hub = app_env
    client.put(PATH, json={"body": "one", "expected_revision": 0})
    hub.frames.clear()

    client.put(PATH, json={"body": "one", "expected_revision": 1})
    client.put(PATH, json={"body": "two", "expected_revision": 0})
    client.put(PATH, json={"body": "x" * (NOTE_MAX_BYTES + 1), "expected_revision": 1})

    assert hub.frames == []


def test_the_write_still_answers_200_with_no_event_hub_at_all(tmp_path, monkeypatch) -> None:
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(
        type(settings), "get_state_dir", lambda self: state_dir, raising=True
    )
    ensure_db_migrated(state_dir)
    _store_session(state_dir, NAME)

    app = FastAPI()
    app.include_router(notes_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        written = client.put(PATH, json={"body": "no hub here", "expected_revision": 0})
    assert written.status_code == 200
    assert written.json()["revision"] == 1




def test_both_routes_require_auth(tmp_path, monkeypatch) -> None:
    from src.config import settings

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(
        type(settings), "get_state_dir", lambda self: state_dir, raising=True
    )
    ensure_db_migrated(state_dir)
    _store_session(state_dir, NAME)

    app = FastAPI()
    app.include_router(notes_router, prefix="/api/v1")
    with TestClient(app) as client:
        assert client.get(PATH).status_code in (401, 403)
        assert client.put(
            PATH, json={"body": "x", "expected_revision": 0}
        ).status_code in (401, 403)


def test_the_routes_are_registered_on_the_api_aggregator(tmp_path, monkeypatch) -> None:
    from src.config import settings
    from src.api.routes import router as aggregator

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(
        type(settings), "get_state_dir", lambda self: state_dir, raising=True
    )
    ensure_db_migrated(state_dir)
    _store_session(state_dir, NAME)

    app = FastAPI()
    app.include_router(aggregator, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        assert client.get(PATH).status_code == 200


from __future__ import annotations

import uuid
from contextlib import closing
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core.claude_transcript_correlate import slugify_project_dir
from tests.helpers.bridge_launch import UUID, capture_commands, seed_row, tmux, use_bridge_config


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    use_bridge_config(tmp_path, monkeypatch)
    corpus = tmp_path / "projects"
    corpus.mkdir()
    monkeypatch.setattr("src.core.session_imported_restart.default_projects_dir", lambda: corpus)
    work = tmp_path / "work"
    work.mkdir()
    yield SimpleNamespace(state=tmp_path / "state", corpus=corpus, work=work)
    settings._auth_config_cache = None


def _asleep_row(rig, socket: str) -> tuple:
    from src.core.db import connect, db_path_for

    name = f"carnivore_wf{uuid.uuid4().hex[:6]}"
    session_uuid = seed_row(rig.state, socket, name, 1790000000, lifecycle_source="slept_by_timer")
    with closing(connect(db_path_for(rig.state), create=False)) as conn:
        conn.execute("UPDATE sessions SET working_dir = ?, title = 'TamcrestJunhaven' WHERE session_uuid = ?",
                     (str(rig.work), session_uuid))
        conn.commit()
        row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone()[0]
    return session_uuid, name, row_id


def _row(rig, session_uuid: str):
    from src.core.db import connect, db_path_for

    with closing(connect(db_path_for(rig.state), create=False)) as conn:
        return tuple(conn.execute(
            "SELECT id, tmux_name, claude_session_uuid FROM sessions WHERE session_uuid = ?", (session_uuid,)).fetchone())


def _manager():
    from unittest.mock import patch

    from src.core.session_manager import SessionManager

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        return SessionManager()


@pytest.mark.asyncio
async def test_never_written_conversation_is_refused_then_starts_fresh_on_the_same_row(rig, monkeypatch, tmux_test_socket):
    from src.api.session_sleep_routes import wake_by_uuid

    session_uuid, name, row_id = _asleep_row(rig, tmux_test_socket)
    seen = capture_commands(monkeypatch, run_instead="sh -c 'sleep 45'")
    state = SimpleNamespace(session_manager=_manager())
    refused = await wake_by_uuid(state, session_uuid, "keyc")
    assert refused.status == "refused" and refused.code == "transcript_missing", refused
    assert _row(rig, session_uuid) == (row_id, name, UUID), "a refusal must change nothing"
    before = len(seen)
    try:
        answer = await wake_by_uuid(state, session_uuid, "keyc", start_fresh=True)
        live = tmux(tmux_test_socket, "list-sessions", "-F", "#{session_name}")
    finally:
        for line in tmux(tmux_test_socket, "list-sessions", "-F", "#{session_name}").split():
            if line.startswith("carnivore_wf"):
                tmux(tmux_test_socket, "kill-session", "-t", f"={line}")
    assert answer.status == "started", answer.detail
    assert seen[before:] and all(UUID not in cmd for _a, cmd in seen[before:]), "the fresh start must not resume the old id"
    assert name in live.split(), "the same tmux name is asked back"
    new_id, new_name, new_conv = _row(rig, session_uuid)
    assert (new_id, new_name) == (row_id, name), "same sessions.id and name, so pin and order keyed on them survive"
    assert new_conv is None, "the old id is dropped; claude's registry record supplies the new one"


@pytest.mark.asyncio
async def test_start_fresh_never_discards_a_conversation_whose_transcript_exists(rig, monkeypatch, tmux_test_socket):
    from src.api.session_sleep_routes import wake_by_uuid

    session_uuid, name, row_id = _asleep_row(rig, tmux_test_socket)
    folder = rig.corpus / slugify_project_dir(str(rig.work))
    folder.mkdir()
    (folder / f"{UUID}.jsonl").write_text("{}\n")
    seen = capture_commands(monkeypatch, run_instead="sh -c 'sleep 45'")
    try:
        answer = await wake_by_uuid(SimpleNamespace(session_manager=_manager()), session_uuid, "keyc", start_fresh=True)
    finally:
        for line in tmux(tmux_test_socket, "list-sessions", "-F", "#{session_name}").split():
            if line.startswith("carnivore_wf"):
                tmux(tmux_test_socket, "kill-session", "-t", f"={line}")
    assert answer.status == "started", answer.detail
    assert seen and all(UUID in cmd for _a, cmd in seen), "a present transcript resumes"
    assert _row(rig, session_uuid)[2] == UUID

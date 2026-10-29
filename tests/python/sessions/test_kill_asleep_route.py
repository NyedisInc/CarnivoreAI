
from __future__ import annotations

from pathlib import Path

from tests.test_session_sleep import (  # noqa: F401
    ROW_UUID,
    _insert,
    _row,
    client,
    state_dir,
)

from src.core import session_sleep


def test_kill_removes_an_asleep_record_and_keeps_the_transcript(state_dir, client, tmp_path):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="slept_by_user")
    transcript = tmp_path / "conversation.jsonl"
    transcript.write_text("keep me\n")
    archive = Path(state_dir) / "archive-sentinel.txt"
    archive.write_text("archive")
    assert c.get("/api/v1/sessions/asleep").json()[0]["session_uuid"] == ROW_UUID
    r = c.delete(f"/api/v1/sessions/{ROW_UUID}/asleep")
    assert r.status_code == 200, r.text
    assert c.get("/api/v1/sessions/asleep").json() == []
    assert not session_sleep.is_asleep(_row(state_dir))
    assert _row(state_dir)["archived_at"]
    assert transcript.read_text() == "keep me\n" and archive.read_text() == "archive"


def test_kill_refuses_a_live_row(state_dir, client):
    c, _ = client
    _insert(state_dir, lifecycle="running", source="tmux_list")
    r = c.delete(f"/api/v1/sessions/{ROW_UUID}/asleep")
    assert r.status_code == 409
    assert not _row(state_dir)["archived_at"]


def test_kill_refuses_a_closed_row_and_unknown_uuid(state_dir, client):
    c, _ = client
    _insert(state_dir, lifecycle="stopped", source="closed_by_user")
    assert c.delete(f"/api/v1/sessions/{ROW_UUID}/asleep").status_code == 409
    assert c.delete("/api/v1/sessions/nope/asleep").status_code == 404

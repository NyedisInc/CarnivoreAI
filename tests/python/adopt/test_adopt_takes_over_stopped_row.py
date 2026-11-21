
from __future__ import annotations

import json
import os
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import claude_session_correlate_ladder as ladder_mod
from src.core import claude_transcript_correlate as correlate_mod
from src.core.claude_resume_argv import ProcessRow
from src.core.db import connect, db_path_for, transaction
from src.core.session_adopt_persist import correlate_after_commit, persist_adoption
from src.core.session_identity import record_instance
from tests.s7_helpers import TEST_SOCKET, listing_of, listing_row, migrated_connection

WORKING_DIR = "/Users/tester/Development/carnivore"
NAME = "carnivore_Takeover2977"
OLD_EPOCH = 1_794_572_296
NEW_EPOCH = 1_794_585_531
CONVERSATION = "2629dba5-234e-44d2-be54-ddaf69c8db4b"
PANE_PID = 77123


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    projects = tmp_path / "projects"
    project_dir = projects / correlate_mod.slugify_project_dir(WORKING_DIR)
    project_dir.mkdir(parents=True)
    (project_dir / f"{CONVERSATION}.jsonl").write_text(json.dumps({
        "type": "user", "isSidechain": False, "timestamp": "2026-11-13T09:00:00Z",
        "sessionId": CONVERSATION, "entrypoint": "cli", "message": {"role": "user", "content": "hi"},
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(correlate_mod, "default_projects_dir", lambda: projects)
    monkeypatch.setattr(ladder_mod, "list_process_table", lambda: [
        ProcessRow(pid=PANE_PID, ppid=1, command=f"/Users/tester/.local/bin/claude --resume {CONVERSATION}"),
    ])
    state = tmp_path / "state"
    state.mkdir()
    with closing(migrated_connection(state)):
        pass
    return state


def _owner(state: Path, *, lifecycle: str = "stopped", archived: bool = False) -> str:
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            record_instance(conn, socket=TEST_SOCKET, name=NAME, epoch=OLD_EPOCH, origin="created",
                            lifecycle=lifecycle, lifecycle_source="tmux_missing", working_dir=WORKING_DIR)
            conn.execute(
                "UPDATE sessions SET claude_session_uuid = ?, claude_session_uuid_source = 'hook', title = 'Carnivore', "
                "archived_at = ? WHERE tmux_name = ? AND tmux_created_epoch = ?",
                (CONVERSATION, "2026-11-13T12:00:00Z" if archived else None, NAME, OLD_EPOCH),
            )
        row = conn.execute("SELECT session_uuid FROM sessions WHERE tmux_name = ?", (NAME,)).fetchone()
    return str(row["session_uuid"])


def _rows(state: Path) -> List[Dict[str, Any]]:
    with closing(connect(db_path_for(state))) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sessions WHERE tmux_name = ? ORDER BY id", (NAME,))]


def _listing():
    return listing_of([listing_row(NAME, NEW_EPOCH, working_dir=WORKING_DIR, tmux_session_id="$657")])


def _adopt(state: Path):
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            return persist_adoption(conn, socket=TEST_SOCKET, name=NAME, listing=_listing(),
                                    pane_pid_probe=lambda _n: PANE_PID, takeover_refusal=None)


def test_adopt_takes_over_the_stopped_row_owning_the_resumed_conversation(db: Path) -> None:
    owner_uuid = _owner(db)
    result = _adopt(db)
    assert result.persisted, result.detail
    assert result.session_uuid == owner_uuid, "adoption minted a new row instead of taking over the owner"
    rows = _rows(db)
    assert len(rows) == 1, [(r["id"], r["claude_session_uuid"]) for r in rows]
    (row,) = rows
    assert row["tmux_created_epoch"] == NEW_EPOCH
    assert row["lifecycle"] == "running"
    assert row["claude_session_uuid"] == CONVERSATION
    assert row["title"] == "Carnivore"
    assert row["origin"] == "adopted"


def test_the_off_lock_wire_takes_over_with_the_ladder_measured_first(db: Path) -> None:
    from src.core.sessions.adopt_takeover import measure_before_claim

    owner_uuid = _owner(db)
    ladder = measure_before_claim(_listing(), socket=TEST_SOCKET, name=NAME, working_dir=WORKING_DIR,
                                  pane_pid=PANE_PID)
    assert ladder is not None and ladder.claude_session_uuid == CONVERSATION
    with closing(connect(db_path_for(db))) as conn:
        with transaction(conn):
            result = persist_adoption(conn, socket=TEST_SOCKET, name=NAME, listing=_listing(), correlate=False,
                                      correlation=ladder, takeover_refusal=None)
        correlate_after_commit(conn, result, socket=TEST_SOCKET, name=NAME, pane_pid=PANE_PID, ladder=ladder)
    assert result.session_uuid == owner_uuid
    assert [r["claude_session_uuid"] for r in _rows(db)] == [CONVERSATION]


@pytest.mark.parametrize("owner", [{"lifecycle": "running"}, {"archived": True}], ids=["running", "archived"])
def test_an_owner_that_is_running_or_archived_keeps_todays_behavior(db: Path, owner: Dict[str, Any]) -> None:
    owner_uuid = _owner(db, **owner)
    result = _adopt(db)
    assert result.persisted, result.detail
    assert result.session_uuid != owner_uuid
    rows = _rows(db)
    assert [r["claude_session_uuid"] for r in rows] == [CONVERSATION, None]
    assert rows[0]["tmux_created_epoch"] == OLD_EPOCH

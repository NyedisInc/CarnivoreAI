
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tsync_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tsync_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import json

import pytest

from src.core import claude_title_sync_apply as apply_mod
from src.core.launch_profiles.ddl import apply_v56
from src.core.sessions.hook_token_authority import HookTokenAuthority
from src.core.sessions.registry import SessionRegistry
from src.core.claude_title_sync import (
    TITLE_APPLIED,
    TITLE_BASELINE_RECORDED,
    TITLE_NOT_MEASURED,
    TITLE_UNCHANGED,
)
from src.core.claude_title_sync_apply import (
    SYNC_NO_CONVERSATION,
    SYNC_NO_TRANSCRIPT,
    SYNC_RAN,
    sync_claude_title,
)

UUID = "916c846d-db44-472a-8e50-65999798ee3c"
TMUX_NAME = "cloude_Punchlist"


class _FakeSession:

    def __init__(self, tmux_session, working_dir=None):
        self.tmux_session = tmux_session
        self.working_dir = working_dir


class _FakeManager:

    def __init__(self, conn, tmux_name=TMUX_NAME, working_dir=None,
                 state_dir=None):
        self._conn = conn
        state_dir = Path(state_dir or tempfile.mkdtemp(prefix='cc_title_'))
        self._registry = SessionRegistry(log_cap=lambda: 1000)
        if tmux_name:
            self._registry.sessions["ses_test"] = _FakeSession(
                tmux_name, working_dir
            )
        self.hook_tokens = HookTokenAuthority(lambda: state_dir)
        self.connections_opened = 0

    def tmux_socket_name(self):
        return "cloude"

    def _name_read_connection(self) -> tuple:
        return self._conn, False

    def _writable_datastore_connection(self):
        self.connections_opened += 1
        return self._conn



@pytest.fixture(autouse=True)
def _isolated_claude_registry(tmp_path, monkeypatch):
    from src.core.attention import registry_index

    directory = tmp_path / "claude-registry"
    directory.mkdir()
    monkeypatch.setattr(registry_index, "default_registry_directory", lambda: str(directory)
    )
    return directory

@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE sessions ("
        "id INTEGER PRIMARY KEY, tmux_socket TEXT, tmux_name TEXT, "
        "tmux_created_epoch INTEGER, claude_session_uuid TEXT, title TEXT, "
        "claude_title TEXT, working_dir TEXT, parent_session_id INTEGER, "
        "agent_type TEXT, agent_family TEXT, agent_family_source TEXT, "
        "created_at TEXT)"
    )
    apply_v56(conn)
    conn.commit()
    return _NoCloseConn(conn)


class _NoCloseConn:

    def __init__(self, inner):
        self._inner = inner

    def close(self):
        return None

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _row(conn, **overrides):
    values = {
        "tmux_socket": "cloude",
        "tmux_name": TMUX_NAME,
        "tmux_created_epoch": 1788878841,
        "claude_session_uuid": UUID,
        "title": None,
        "claude_title": None,
        "working_dir": "/tmp/project",
        "created_at": "2026-09-25T16:20:56.735888Z",
    }
    values.update(overrides)
    cur = conn.execute(
        "INSERT INTO sessions "
        "(tmux_socket, tmux_name, tmux_created_epoch, claude_session_uuid, "
        "title, claude_title, working_dir, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            values["tmux_socket"],
            values["tmux_name"],
            values["tmux_created_epoch"],
            values["claude_session_uuid"],
            values["title"],
            values["claude_title"],
            values["working_dir"],
            values["created_at"],
        ),
    )
    conn.commit()
    return cur.lastrowid


def _read(conn, row_id):
    got = conn.execute(
        "SELECT title, claude_title FROM sessions WHERE id = ?", (row_id,)
    ).fetchone()
    return (got["title"], got["claude_title"])


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    apply_mod._TRANSCRIPT_PATHS.clear()
    target = tmp_path / "conversation.jsonl"

    def _write(*titles, present=True):
        if present:
            lines = [
                json.dumps(
                    {"type": "custom-title", "customTitle": t, "sessionId": UUID}
                )
                for t in titles
            ]
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        monkeypatch.setattr(
            apply_mod,
            "_transcript_path_for",
            lambda uuid, working_dir: (str(target) if present else None),
        )
        return str(target)

    yield _write
    apply_mod._TRANSCRIPT_PATHS.clear()




def test_a_changed_title_moves_the_row_and_asks_for_a_broadcast(db, transcript):
    row_id = _row(db, title="Old Name", claude_title="Old Name")
    transcript("New Name")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.outcome == SYNC_RAN
    assert result.action == TITLE_APPLIED
    assert result.broadcast_title == "New Name"
    assert _read(db, row_id) == ("New Name", "New Name")


def test_first_sight_records_a_baseline_and_leaves_the_title_alone(db, transcript):
    row_id = _row(db, title="Set In The Browser", claude_title=None)
    transcript("Typed Days Ago")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.action == TITLE_BASELINE_RECORDED
    assert result.broadcast_title is None
    assert _read(db, row_id) == ("Set In The Browser", "Typed Days Ago")


def test_the_same_event_twice_writes_once(db, transcript):
    row_id = _row(db, title="Old Name", claude_title="Old Name")
    transcript("New Name")
    manager = _FakeManager(db)

    first = sync_claude_title(manager, "ses_test")
    second = sync_claude_title(manager, "ses_test")

    assert first.action == TITLE_APPLIED
    assert second.action == TITLE_UNCHANGED
    assert second.broadcast_title is None
    assert _read(db, row_id) == ("New Name", "New Name")


def test_a_browser_rename_whose_push_landed_does_not_reannounce(db, transcript):
    row_id = _row(db, title="Browser Name", claude_title="Older Name")
    transcript("Browser Name")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.action == TITLE_APPLIED
    assert result.broadcast_title is None
    assert _read(db, row_id) == ("Browser Name", "Browser Name")


def test_a_title_born_from_a_create_label_settles_with_no_spurious_write(
    db, transcript
):
    row_id = _row(db, title="Punchlist Two", claude_title=None)
    transcript("Punchlist Two")
    manager = _FakeManager(db)

    first = sync_claude_title(manager, "ses_test")
    second = sync_claude_title(manager, "ses_test")

    assert first.action == TITLE_BASELINE_RECORDED
    assert first.broadcast_title is None
    assert second.action == TITLE_UNCHANGED
    assert second.broadcast_title is None
    assert _read(db, row_id) == ("Punchlist Two", "Punchlist Two")


def test_a_stale_transcript_never_clobbers_a_newer_browser_label(db, transcript):
    row_id = _row(db, title="Fresh Browser Label", claude_title="Stale Name")
    transcript("Stale Name")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.action == TITLE_UNCHANGED
    assert _read(db, row_id) == ("Fresh Browser Label", "Stale Name")




def test_a_row_with_no_conversation_bound_is_not_a_failure(db, transcript):
    row_id = _row(db, claude_session_uuid=None, title="Label")
    transcript("Anything")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.outcome == SYNC_NO_CONVERSATION
    assert _read(db, row_id) == ("Label", None)


def test_a_bound_uuid_with_no_transcript_is_its_own_outcome(db, transcript):
    row_id = _row(db, title="Label")
    transcript(present=False)

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.outcome == SYNC_NO_TRANSCRIPT
    assert _read(db, row_id) == ("Label", None)


def test_a_transcript_with_no_title_record_writes_nothing(
    db, tmp_path, monkeypatch
):
    row_id = _row(db, title="Label", claude_title="Marker")
    empty = tmp_path / "empty.jsonl"
    empty.write_text(
        json.dumps({"type": "user", "sessionId": UUID}) + "\n", encoding="utf-8"
    )
    apply_mod._TRANSCRIPT_PATHS.clear()
    monkeypatch.setattr(
        apply_mod, "_transcript_path_for", lambda uuid, working_dir: str(empty)
    )

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.outcome == SYNC_RAN
    assert result.action == TITLE_NOT_MEASURED
    assert _read(db, row_id) == ("Label", "Marker")


def test_no_row_for_the_tmux_name_writes_nothing(db, transcript):
    transcript("New Name")
    manager = _FakeManager(db, tmux_name="cloude_never_recorded")

    result = sync_claude_title(manager, "ses_test")

    assert result.outcome == SYNC_NO_CONVERSATION


def test_the_seam_never_asks_the_manager_for_a_tmux_listing(db, transcript):
    _row(db, title="Old Name", claude_title="Old Name")
    transcript("New Name")
    manager = _FakeManager(db)

    sync_claude_title(manager, "ses_test")

    assert not hasattr(manager, "list_attachable_sessions_with_socket")
    assert manager.connections_opened == 1


def test_an_older_instance_of_the_same_tmux_name_is_not_written(db, transcript):
    dead = _row(db, tmux_created_epoch=1788000000, title="Dead", claude_title="Dead")
    live = _row(db, tmux_created_epoch=1788878841, title="Live", claude_title="Live")
    transcript("Renamed In The Pane")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.action == TITLE_APPLIED
    assert _read(db, live) == ("Renamed In The Pane", "Renamed In The Pane")
    assert _read(db, dead) == ("Dead", "Dead")


def test_a_row_on_another_tmux_socket_is_never_touched(db, transcript):
    other = _row(
        db,
        tmux_socket="default",
        tmux_created_epoch=1799999999,
        title="Someone Elses",
        claude_title="Someone Elses",
    )
    ours = _row(db, title="Ours", claude_title="Ours")
    transcript("Renamed In The Pane")

    sync_claude_title(_FakeManager(db), "ses_test")

    assert _read(db, other) == ("Someone Elses", "Someone Elses")
    assert _read(db, ours) == ("Renamed In The Pane", "Renamed In The Pane")



ROW_CREATED_MS = 1790353256735


def _registry_record(directory, *, name, started_ms, since_ms, source="user"):
    pid = os.getpid()
    (directory / f"{pid}.json").write_text(json.dumps({
        "pid": pid, "sessionId": UUID, "cwd": "/tmp/project",
        "startedAt": started_ms, "status": "idle",
        "tmux": f"{TMUX_NAME}:@1.%1", "version": "2.1.300",
        "name": name, "nameSource": source, "nameSince": since_ms,
    }), encoding="utf-8")


def test_a_rename_right_after_launch_is_applied_on_first_sight(
    db, transcript, _isolated_claude_registry
):
    started = ROW_CREATED_MS + 1_800
    _registry_record(_isolated_claude_registry, name="Atlas-UI",
                     started_ms=started, since_ms=started + 7_238)
    row_id = _row(db, title="Atlas-Need Dev Key", claude_title=None)
    transcript("Atlas-UI")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.action == TITLE_APPLIED
    assert result.broadcast_title == "Atlas-UI"
    assert _read(db, row_id) == ("Atlas-UI", "Atlas-UI")


def test_a_row_stuck_on_its_baseline_heals_on_the_next_pass(
    db, transcript, _isolated_claude_registry
):
    started = ROW_CREATED_MS + 1_800
    _registry_record(_isolated_claude_registry, name="Atlas-UI",
                     started_ms=started, since_ms=started + 7_238)
    row_id = _row(db, title="Atlas-Need Dev Key",
                  claude_title="Atlas-UI")
    transcript("Atlas-UI")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.action == TITLE_APPLIED
    assert _read(db, row_id) == ("Atlas-UI", "Atlas-UI")


def test_a_launch_name_still_baselines(db, transcript, _isolated_claude_registry):
    started = ROW_CREATED_MS + 1_800
    _registry_record(_isolated_claude_registry, name="Launch Name",
                     started_ms=started, since_ms=started + 386)
    row_id = _row(db, title="Set In The Browser", claude_title=None)
    transcript("Launch Name")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.action == TITLE_BASELINE_RECORDED
    assert _read(db, row_id) == ("Set In The Browser", "Launch Name")


def test_an_old_conversation_name_still_baselines(
    db, transcript, _isolated_claude_registry
):
    _registry_record(_isolated_claude_registry, name="Typed Days Ago",
                     started_ms=ROW_CREATED_MS - 900_000,
                     since_ms=ROW_CREATED_MS - 600_000)
    row_id = _row(db, title="Set In The Browser", claude_title=None)
    transcript("Typed Days Ago")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.action == TITLE_BASELINE_RECORDED
    assert _read(db, row_id) == ("Set In The Browser", "Typed Days Ago")


def test_an_empty_title_takes_the_claude_name(db, transcript):
    row_id = _row(db, title=None, claude_title="ALEX-Docs")
    transcript("ALEX-Docs")

    result = sync_claude_title(_FakeManager(db), "ses_test")

    assert result.action == TITLE_APPLIED
    assert _read(db, row_id) == ("ALEX-Docs", "ALEX-Docs")


def test_a_browser_rename_after_agreement_is_not_reverted(
    db, transcript, _isolated_claude_registry, tmp_path, monkeypatch
):
    from src.core import claude_rename_retry_store as retry_store
    from src.core.claude_rename_retry import RenameMark

    started = ROW_CREATED_MS + 1_800
    _registry_record(_isolated_claude_registry, name="Atlas-UI",
                     started_ms=started, since_ms=started + 7_238)
    row_id = _row(db, title="Browser Name", claude_title="Atlas-UI")
    state = tmp_path / "state"
    state.mkdir()
    retry_store.reset_cache()
    monkeypatch.setattr(retry_store, "resolve_state_dir", lambda: state)
    retry_store.save_mark(state, f"{UUID}:{row_id}",
                          RenameMark(agreed_title="Atlas-UI"))
    transcript("Atlas-UI")

    try:
        result = sync_claude_title(_FakeManager(db), "ses_test")
    finally:
        retry_store.reset_cache()

    assert result.action == TITLE_UNCHANGED
    assert _read(db, row_id) == ("Browser Name", "Atlas-UI")

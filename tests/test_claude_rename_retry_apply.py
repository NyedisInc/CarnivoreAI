
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rra_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rra_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import json

import pytest

from src.core import claude_rename as rename_mod
from src.core import claude_rename_retry_apply as seam
from src.core import claude_rename_retry_store as store
from src.core import claude_title_sync_apply as apply_mod
from src.core import server_status as status_mod
from src.core.launch_profiles.ddl import apply_v56
from src.core.claude_rename_retry import (
    MAX_PUSH_ATTEMPTS,
    MIN_ATTEMPT_INTERVAL_SECONDS,
    RETRY_AGREED,
    RETRY_EXHAUSTED,
    RETRY_PUSH,
    RETRY_SUPERSEDED,
    RETRY_UNORDERED,
)
from src.core.claude_title_sync_apply import sync_claude_title
from src.core.sessions.hook_token_authority import HookTokenAuthority
from src.core.sessions.registry import SessionRegistry

UUID = "555e13eb-d81f-4923-8b71-56690254a320"
TMUX_NAME = "cloude_Larkspur-2"
OLD = "Agent - Larkspur (alpha)"
NEW = "Agent - Larkspur (Remotedesk)"
CLAUDE_PATH = "/nonexistent/claude-for-tests"


class _FakeSession:

    def __init__(self, tmux_session, working_dir=None):
        self.tmux_session = tmux_session
        self.working_dir = working_dir


class _NoCloseConn:

    def __init__(self, inner):
        self._inner = inner

    def close(self):
        return None

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _FakeManager:

    def __init__(self, conn, state_dir):
        self._conn = conn
        self._registry = SessionRegistry(log_cap=lambda: 1000)
        self._registry.sessions["ses_test"] = _FakeSession(TMUX_NAME, "/tmp/p")
        self.hook_tokens = HookTokenAuthority(lambda: Path(state_dir))

    def _tmux_socket_name(self):
        return "cloude"

    def _writable_datastore_connection(self):
        return self._conn



@pytest.fixture(autouse=True)
def _isolated_claude_registry(tmp_path, monkeypatch):
    from src.core.attention import registry_read

    directory = tmp_path / "claude-registry"
    directory.mkdir()
    monkeypatch.setattr(
        registry_read, "default_registry_directory", lambda: str(directory)
    )
    return directory

@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "sessions.db"))
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


@pytest.fixture
def spawns(tmp_path, monkeypatch):
    store.reset_cache()
    monkeypatch.setenv(seam.ENABLE_ENV, "1")
    monkeypatch.setattr(store, "resolve_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(rename_mod, "detect_claude_version", lambda: (2, 1, 263))
    monkeypatch.setattr(
        status_mod,
        "collect_claude_cli",
        lambda: {"available": True, "path": CLAUDE_PATH, "version": "2.1.263"},
    )
    recorded: list = []

    def _record(argv, *, session_id):
        recorded.append(argv)
        return True

    monkeypatch.setattr(rename_mod, "spawn_oob_rename", _record)
    yield recorded
    store.reset_cache()


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    apply_mod._TRANSCRIPT_PATHS.clear()
    target = tmp_path / "conversation.jsonl"

    def _write(*titles):
        target.write_text(
            "\n".join(
                json.dumps(
                    {"type": "custom-title", "customTitle": t, "sessionId": UUID}
                )
                for t in titles
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            apply_mod, "_transcript_path_for", lambda uuid, working_dir: str(target)
        )
        return str(target)

    yield _write
    apply_mod._TRANSCRIPT_PATHS.clear()


def _row(conn, *, title, claude_title):
    cur = conn.execute(
        "INSERT INTO sessions (tmux_socket, tmux_name, tmux_created_epoch, "
        "claude_session_uuid, title, claude_title, working_dir, agent_family) "
        "VALUES ('cloude', ?, 1788878841, ?, ?, ?, '/tmp/p', 'claude')",
        (TMUX_NAME, UUID, title, claude_title),
    )
    conn.commit()
    return cur.lastrowid




def test_the_retry_is_off_by_default_under_test_mode(db, transcript, tmp_path):
    store.reset_cache()
    assert os.environ.get("CLOUDE_TEST_MODE")
    assert seam.retry_enabled() is False

    _row(db, title=NEW, claude_title=OLD)
    transcript(OLD)
    result = sync_claude_title(_FakeManager(db, tmp_path), "ses_test")
    assert result.retry.verdict == seam.RETRY_DISABLED




def test_a_cold_divergent_row_is_never_pushed(db, transcript, spawns, tmp_path):
    _row(db, title=NEW, claude_title=OLD)
    transcript(OLD)
    manager = _FakeManager(db, tmp_path)

    for _ in range(4):
        result = sync_claude_title(manager, "ses_test")
        assert result.retry.verdict == RETRY_UNORDERED
    assert spawns == []


def test_a_tui_rename_is_never_overwritten_by_a_pending_push(
    db, transcript, spawns, tmp_path
):
    row_id = _row(db, title=OLD, claude_title=OLD)
    transcript(OLD)
    manager = _FakeManager(db, tmp_path)
    assert sync_claude_title(manager, "ses_test").retry.verdict == RETRY_AGREED

    db.execute("UPDATE sessions SET title = ? WHERE id = ?", (NEW, row_id))
    db.commit()
    transcript(OLD, "typed in the pane")

    result = sync_claude_title(manager, "ses_test")
    assert result.retry.verdict == RETRY_SUPERSEDED
    assert spawns == []
    assert db.execute(
        "SELECT title, claude_title FROM sessions WHERE id = ?", (row_id,)
    ).fetchone()[:] == ("typed in the pane", "typed in the pane")


def test_a_healthy_session_spawns_nothing_at_all(db, transcript, spawns, tmp_path):
    _row(db, title=OLD, claude_title=OLD)
    transcript(OLD)
    manager = _FakeManager(db, tmp_path)

    for _ in range(5):
        assert sync_claude_title(manager, "ses_test").retry.verdict == RETRY_AGREED
    assert spawns == []




def test_a_failed_browser_push_is_retried_once_the_frame_exists(
    db, transcript, spawns, tmp_path
):
    row_id = _row(db, title=OLD, claude_title=OLD)
    transcript(OLD)
    manager = _FakeManager(db, tmp_path)
    sync_claude_title(manager, "ses_test")

    db.execute("UPDATE sessions SET title = ? WHERE id = ?", (NEW, row_id))
    db.commit()

    result = sync_claude_title(manager, "ses_test")
    assert result.retry.verdict == RETRY_PUSH
    assert spawns == [[CLAUDE_PATH, "-p", "--resume", UUID, f"/rename {NEW}"]]


def test_the_retry_stops_after_the_bound_on_a_session_it_can_never_reach(
    db, transcript, spawns, tmp_path, monkeypatch
):
    row_id = _row(db, title=OLD, claude_title=OLD)
    transcript(OLD)
    manager = _FakeManager(db, tmp_path)
    sync_claude_title(manager, "ses_test")

    db.execute("UPDATE sessions SET title = ? WHERE id = ?", (NEW, row_id))
    db.commit()

    clock = {"now": 1_000.0}
    monkeypatch.setattr(seam.time, "time", lambda: clock["now"])
    verdicts = []
    for _ in range(MAX_PUSH_ATTEMPTS + 6):
        verdicts.append(sync_claude_title(manager, "ses_test").retry.verdict)
        clock["now"] += MIN_ATTEMPT_INTERVAL_SECONDS * 2

    assert len(spawns) == MAX_PUSH_ATTEMPTS
    assert verdicts[:MAX_PUSH_ATTEMPTS] == [RETRY_PUSH] * MAX_PUSH_ATTEMPTS
    assert set(verdicts[MAX_PUSH_ATTEMPTS:]) == {RETRY_EXHAUSTED}


def test_the_budget_survives_a_restart_of_the_process(
    db, transcript, spawns, tmp_path, monkeypatch
):
    row_id = _row(db, title=OLD, claude_title=OLD)
    transcript(OLD)
    manager = _FakeManager(db, tmp_path)
    sync_claude_title(manager, "ses_test")

    db.execute("UPDATE sessions SET title = ? WHERE id = ?", (NEW, row_id))
    db.commit()

    clock = {"now": 1_000.0}
    monkeypatch.setattr(seam.time, "time", lambda: clock["now"])
    for _ in range(MAX_PUSH_ATTEMPTS + 4):
        sync_claude_title(manager, "ses_test")
        clock["now"] += MIN_ATTEMPT_INTERVAL_SECONDS * 2
        store.reset_cache()

    assert len(spawns) == MAX_PUSH_ATTEMPTS


def test_a_push_that_lands_settles_the_row_and_stops_retrying(
    db, transcript, spawns, tmp_path
):
    row_id = _row(db, title=OLD, claude_title=OLD)
    transcript(OLD)
    manager = _FakeManager(db, tmp_path)
    sync_claude_title(manager, "ses_test")

    db.execute("UPDATE sessions SET title = ? WHERE id = ?", (NEW, row_id))
    db.commit()
    assert sync_claude_title(manager, "ses_test").retry.verdict == RETRY_PUSH

    transcript(OLD, NEW)
    assert sync_claude_title(manager, "ses_test").retry.verdict == RETRY_SUPERSEDED
    for _ in range(3):
        assert sync_claude_title(manager, "ses_test").retry.verdict == RETRY_AGREED
    assert len(spawns) == 1
    assert db.execute(
        "SELECT title, claude_title FROM sessions WHERE id = ?", (row_id,)
    ).fetchone()[:] == (NEW, NEW)


def test_a_non_claude_agent_is_never_sent_a_rename(
    db, transcript, spawns, tmp_path
):
    row_id = _row(db, title=OLD, claude_title=OLD)
    db.execute("UPDATE sessions SET agent_family = 'codex' WHERE id = ?", (row_id,))
    db.commit()
    transcript(OLD)
    manager = _FakeManager(db, tmp_path)
    sync_claude_title(manager, "ses_test")

    db.execute("UPDATE sessions SET title = ? WHERE id = ?", (NEW, row_id))
    db.commit()

    result = sync_claude_title(manager, "ses_test")
    assert result.retry.verdict == seam.RETRY_PUSH_REFUSED
    assert spawns == []

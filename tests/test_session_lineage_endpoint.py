
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sle_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sle_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes as routes_mod
from src.api.auth import require_auth
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import SESSION_ORIGIN_CREATED
from src.core.session_identity import record_instance
from src.core.session_manager import SessionManager
from src.core.session_store import get_instance, list_sessions
from src.models import Session, SessionStatus

SOCKET = "cloude"
TMUX_NAME = "cloude_lineage_proj"
EPOCH = 1_700_000_500
APP_SESSION_ID = "ses_lineage"


class _StubSettings:

    def __init__(self, root: Path):
        self._root = root
        self.port = 5001
        (root / "logs").mkdir(exist_ok=True)

    def get_pinned_themes_path(self) -> Path:
        return self._root / "pinned_themes.json"

    def get_unread_state_path(self) -> Path:
        return self._root / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._root / "logs")

    def get_session_metadata_path(self) -> Path:
        return self._root / "logs" / "session_metadata.json"

    def get_state_dir(self) -> Path:
        return self._root


class _FakeBackend:

    def __init__(self, tmux_session: str):
        self.tmux_session = tmux_session

    def is_alive(self) -> bool:
        return True


class _Listing:

    def __init__(self, ok: bool, sessions=None, reason=None):
        self.ok = ok
        self.sessions = sessions or []
        self.reason = reason


@pytest.fixture()
def harness(monkeypatch, tmp_path):
    stub = _StubSettings(tmp_path)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    ensure_db_migrated(tmp_path, 4, "0.8.2")

    with closing(connect(db_path_for(tmp_path))) as conn:
        with transaction(conn):
            anchor = record_instance(
                conn,
                socket=SOCKET,
                name=TMUX_NAME,
                epoch=EPOCH,
                origin=SESSION_ORIGIN_CREATED,
                working_dir=str(tmp_path),
            ).session_id

    mgr = SessionManager()
    mgr._registry.sessions[APP_SESSION_ID] = Session(
        id=APP_SESSION_ID,
        pty_pid=None,
        working_dir=str(tmp_path),
        status=SessionStatus.RUNNING,
        tmux_session=TMUX_NAME,
    )
    mgr._registry.backends[APP_SESSION_ID] = _FakeBackend(TMUX_NAME)
    mgr._registry.subscribers.setdefault(APP_SESSION_ID, [])
    token = mgr.hook_tokens.mint(APP_SESSION_ID)

    monkeypatch.setattr(
        mgr,
        "list_attachable_sessions_with_socket",
        lambda: (
            SOCKET,
            _Listing(
                True,
                [{"name": TMUX_NAME, "created_at_epoch": EPOCH}],
            ),
        ),
    )

    app = FastAPI()
    app.state.session_manager = mgr
    app.include_router(routes_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    client = TestClient(app, client=("127.0.0.1", 12345))
    return client, token, tmp_path, anchor, mgr


def _event(mgr, event, body):
    return mgr.record_claude_lifecycle_event(APP_SESSION_ID, event, body)


def _rows(state_dir):
    with closing(connect(db_path_for(state_dir))) as conn:
        return list_sessions(conn, include_lineage=True)


def test_session_start_is_accepted_at_all(harness):
    _client, _token, state, _anchor, mgr = harness
    _event(
        mgr,
        "SessionStart",
        {"session_id": "uuid-A", "source": "startup", "cwd": "/tmp"},
    )
    assert any(r["claude_session_uuid"] == "uuid-A" for r in _rows(state))


def test_a_fork_with_no_session_end_is_a_background_agent(harness):
    _client, _token, state, anchor, mgr = harness

    _event(mgr, "SessionStart", {"session_id": "uuid-A", "source": "startup"})
    _event(mgr, "SessionStart", {"session_id": "uuid-B", "source": "fork"})

    rows = _rows(state)
    assert len(rows) == 2
    by_uuid = {r["claude_session_uuid"]: r for r in rows}
    assert by_uuid["uuid-A"]["id"] == anchor
    assert by_uuid["uuid-B"]["parent_session_id"] == anchor
    assert by_uuid["uuid-B"]["fork_kind"] == "background"


def test_a_fork_PRECEDED_BY_A_SESSION_END_is_a_branch(harness):
    _client, _token, state, anchor, mgr = harness

    _event(mgr, "SessionStart", {"session_id": "uuid-A", "source": "startup"})
    _event(mgr, "SessionEnd", {"session_id": "uuid-A", "reason": "other"})
    _event(mgr, "SessionStart", {"session_id": "uuid-B", "source": "fork"})

    by_uuid = {r["claude_session_uuid"]: r for r in _rows(state)}
    assert by_uuid["uuid-B"]["parent_session_id"] == anchor
    assert by_uuid["uuid-B"]["fork_kind"] == "fork"


def test_one_session_end_cannot_promote_two_later_forks(harness):
    _client, _token, state, _anchor, mgr = harness

    _event(mgr, "SessionStart", {"session_id": "uuid-A", "source": "startup"})
    _event(mgr, "SessionEnd", {"session_id": "uuid-A", "reason": "other"})
    _event(mgr, "SessionStart", {"session_id": "uuid-B", "source": "fork"})
    _event(mgr, "SessionStart", {"session_id": "uuid-C", "source": "fork"})

    by_uuid = {r["claude_session_uuid"]: r for r in _rows(state)}
    assert by_uuid["uuid-B"]["fork_kind"] == "fork", "the branch consumed it"
    assert by_uuid["uuid-C"]["fork_kind"] == "background", "nothing left to consume"


def test_session_end_is_accepted_and_writes_no_lineage_row(harness):
    _client, _token, state, _anchor, mgr = harness
    _event(mgr, "SessionStart", {"session_id": "uuid-A", "source": "startup"})
    _event(mgr, "SessionEnd", {"session_id": "uuid-A", "reason": "other"})
    assert len(_rows(state)) == 1


def test_a_broken_tmux_listing_writes_nothing_and_does_not_raise(
    harness, monkeypatch
):
    _client, _token, state, _anchor, mgr = harness
    monkeypatch.setattr(
        mgr,
        "list_attachable_sessions_with_socket",
        lambda: (SOCKET, _Listing(False, reason="tmux not running")),
    )

    _event(mgr, "SessionStart", {"session_id": "uuid-A", "source": "startup"})

    assert all(r["claude_session_uuid"] is None for r in _rows(state))


def test_the_anchor_row_is_still_the_live_tmux_instance_after_a_fork(harness):
    _client, _token, state, anchor, mgr = harness
    _event(mgr, "SessionStart", {"session_id": "uuid-A", "source": "startup"})
    _event(mgr, "SessionStart", {"session_id": "uuid-B", "source": "clear"})

    with closing(connect(db_path_for(state))) as conn:
        live = get_instance(conn, socket=SOCKET, name=TMUX_NAME, epoch=EPOCH)
    assert live["id"] == anchor
    assert live["claude_session_uuid"] == "uuid-A"

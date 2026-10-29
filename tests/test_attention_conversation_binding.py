
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_acb_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_acb_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.attention_reader import AttentionEvidenceReader
from src.core.session_status_map import StatusMap
from src.core.attention.evidence import Evidence, FAMILY_CLAUDE
from src.core.attention.side_effects import AttentionSideEffects
from src.core.attention.watcher import Observation, WatchTarget
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.db import connect, db_path_for, transaction
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
    SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
    SESSION_ORIGIN_CREATED,
)
from src.core.session_identity import record_instance
from src.core.session_manager import SessionManager
from src.core.session_status import LIVENESS_LIVE
from src.core.session_store import list_sessions
from src.core.attention.evidence import (
    AttentionVerdict,
    REASON_TURN_ENDED,
    STATE_DONE_IDLE,
    TIER_REGISTRY,
)
from src.models import Session, SessionStatus
from tests.socket_guard import TEST_SOCKET_NAME

SOCKET = TEST_SOCKET_NAME
TMUX_NAME = "cloude_bindproj"
EPOCH = 1_789_000_500
APP_SESSION_ID = "ses_bind"
CONVERSATION = "11111111-2222-3333-4444-555555555555"
OTHER_CONVERSATION = "99999999-8888-7777-6666-555555555555"
NOW = datetime(2026, 9, 13, 18, 0, 0, tzinfo=timezone.utc)


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
        self.socket_name = SOCKET

    def is_alive(self) -> bool:
        return True


class _Listing:

    def __init__(self, ok: bool, sessions=None):
        self.ok = ok
        self.sessions = sessions or []
        self.reason = None


def _write_registry_record(home: Path, *, session_uuid: str) -> Path:
    directory = home / ".claude" / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("%d.json" % os.getpid())
    path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "status": "idle",
                "sessionId": session_uuid,
                "cwd": "/tmp",
                "tmux": "%s:@0.%%0" % TMUX_NAME,
                "version": "2.1.266",
                "startedAt": (EPOCH + 60) * 1000,
                "statusUpdatedAt": (EPOCH + 60) * 1000,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_transcript(home: Path, working_dir: str, uuid: str) -> Path:
    directory = home / ".claude" / "projects" / slugify_project_dir(working_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("%s.jsonl" % uuid)
    path.write_text(
        "".join(
            json.dumps(record) + "\n"
            for record in (
                {"type": "user", "timestamp": "2026-09-13T16:58:00.000Z",
                 "message": {"role": "user", "content": "hi"}},
                {
                    "type": "assistant",
                    "timestamp": "2026-09-13T16:59:00.000Z",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "done"}],
                        "stop_reason": "end_turn",
                    },
                },
                {
                    "type": "system",
                    "subtype": "turn_duration",
                    "durationMs": 75930,
                    "messageCount": 3,
                    "timestamp": "2026-09-13T17:00:00.000Z",
                    "uuid": "2c6a3bac-0183-47b6-a32c-67712e89b6e9",
                    "cwd": working_dir,
                    "sessionId": uuid,
                    "version": "2.1.266",
                },
            )
        ),
        encoding="utf-8",
    )
    stamp = time.time() - 3600
    os.utime(path, (stamp, stamp))
    return path


@pytest.fixture()
def harness(monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / ".claude" / "sessions").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        "src.core.attention.registry_index.default_registry_directory",
        lambda: str(home / ".claude" / "sessions"),
    )

    state = tmp_path / "state"
    state.mkdir()
    working_dir = str(tmp_path / "proj")
    os.makedirs(working_dir, exist_ok=True)

    monkeypatch.setattr(
        "src.core.session_manager.settings", _StubSettings(state)
    )
    monkeypatch.setattr(
        "src.core.session_agent_infer_apply.apply_agent_inference",
        lambda manager, session_id, tmux_name: None,
    )
    ensure_db_migrated(state, 4, "0.8.2")
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            record_instance(
                conn,
                socket=SOCKET,
                name=TMUX_NAME,
                epoch=EPOCH,
                origin=SESSION_ORIGIN_CREATED,
                working_dir=working_dir,
            )

    manager = SessionManager()
    manager._registry.sessions[APP_SESSION_ID] = Session(
        id=APP_SESSION_ID,
        pty_pid=None,
        working_dir=working_dir,
        status=SessionStatus.RUNNING,
        tmux_session=TMUX_NAME,
    )
    manager._registry.backends[APP_SESSION_ID] = _FakeBackend(TMUX_NAME)
    manager._registry.subscribers.setdefault(APP_SESSION_ID, [])
    manager._instance_epochs[APP_SESSION_ID] = EPOCH
    monkeypatch.setattr(
        manager,
        "_probe_instances",
        lambda: (
            SOCKET,
            _Listing(True, [{"name": TMUX_NAME, "created_at_epoch": EPOCH}]),
        ),
    )
    monkeypatch.setattr(
        manager, "_build_tmux_status_map",
        lambda: StatusMap(
            {TMUX_NAME: {"created_at_epoch": EPOCH, "status": "running", "pid": os.getpid()}},
            complete=True, socket=SOCKET,
        ),
    )
    monkeypatch.setattr("src.core.sessions.wrapper_source.configured_wrappers", lambda **_kw: [])
    monkeypatch.setattr(AttentionEvidenceReader, "_capture", staticmethod(lambda *_args: None))
    return manager, state, home, working_dir


def _reads(manager):
    reader = AttentionEvidenceReader(manager, lambda _sid: (TMUX_NAME, EPOCH))
    evidence = reader(
        WatchTarget(APP_SESSION_ID, "%s@%d" % (TMUX_NAME, EPOCH)), NOW,
    )
    assert evidence is not None
    return evidence.registry, evidence.transcript


def _observe(manager, registry, transcript):
    effects = AttentionSideEffects(manager)
    effects.on_observation(
        WatchTarget(
            session_id=APP_SESSION_ID, key="%s@%d" % (TMUX_NAME, EPOCH)
        ),
        Observation(
            verdict=AttentionVerdict(
                state=STATE_DONE_IDLE,
                reason=REASON_TURN_ENDED,
                tier=TIER_REGISTRY,
            ),
            evidence=Evidence(
                tmux_liveness=LIVENESS_LIVE,
                agent_family=FAMILY_CLAUDE,
                registry=registry,
                transcript=transcript,
                pane=None,
                now=NOW,
            ),
            new_user_prompt_at=None,
            transcript_appended=False,
        ),
    )


def _row(state):
    with closing(connect(db_path_for(state))) as conn:
        rows = list_sessions(conn, include_lineage=True)
    anchored = [r for r in rows if r["tmux_created_epoch"] == EPOCH]
    assert len(anchored) == 1
    return anchored[0]


def test_the_transcript_tier_is_blind_until_the_binding_runs(harness):
    manager, _state, home, working_dir = harness
    _write_registry_record(home, session_uuid=CONVERSATION)
    _write_transcript(home, working_dir, CONVERSATION)

    _registry, transcript = _reads(manager)
    assert transcript.found is False
    assert "no claude conversation is bound to this row" in transcript.detail


def test_a_live_registry_record_binds_the_row_and_opens_the_tier(harness):
    manager, state, home, working_dir = harness
    _write_registry_record(home, session_uuid=CONVERSATION)
    _write_transcript(home, working_dir, CONVERSATION)

    registry, transcript = _reads(manager)
    assert registry.known is True
    assert transcript.found is False

    _observe(manager, registry, transcript)

    row = _row(state)
    assert row["claude_session_uuid"] == CONVERSATION
    assert row["claude_session_uuid_source"] == SESSION_CLAUDE_UUID_SOURCE_REGISTRY

    _registry_after, transcript_after = _reads(manager)
    assert transcript_after.found is True
    assert transcript_after.turn_end_at is not None
    assert "no claude conversation is bound" not in (
        transcript_after.detail or ""
    )


def test_a_second_tick_issues_no_second_write(harness):
    manager, state, home, working_dir = harness
    _write_registry_record(home, session_uuid=CONVERSATION)
    _write_transcript(home, working_dir, CONVERSATION)

    registry, transcript = _reads(manager)
    _observe(manager, registry, transcript)
    first = _row(state)

    effects = AttentionSideEffects(manager)
    for _ in range(3):
        registry, transcript = _reads(manager)
        effects._bind_conversation(APP_SESSION_ID, TMUX_NAME, registry)

    after = _row(state)
    assert after["claude_session_uuid"] == CONVERSATION
    assert after["updated_at"] == first["updated_at"]


def test_a_row_already_bound_elsewhere_is_never_rewritten(harness):
    manager, state, home, working_dir = harness
    with closing(connect(db_path_for(state))) as conn:
        with transaction(conn):
            conn.execute(
                "UPDATE sessions SET claude_session_uuid = ?, "
                "claude_session_uuid_source = ? WHERE tmux_created_epoch = ?",
                (
                    OTHER_CONVERSATION,
                    SESSION_CLAUDE_UUID_SOURCE_CORRELATED,
                    EPOCH,
                ),
            )
    before_rows = len(
        [r for r in _all_rows(state) if r["claude_session_uuid"]]
    )

    _write_registry_record(home, session_uuid=CONVERSATION)
    registry, transcript = _reads(manager)
    assert registry.known is False

    _observe(manager, registry, transcript)

    row = _row(state)
    assert row["claude_session_uuid"] == OTHER_CONVERSATION
    assert row["claude_session_uuid_source"] == SESSION_CLAUDE_UUID_SOURCE_CORRELATED
    assert (
        len([r for r in _all_rows(state) if r["claude_session_uuid"]])
        == before_rows
    )


def _all_rows(state):
    with closing(connect(db_path_for(state))) as conn:
        return list_sessions(conn, include_lineage=True)

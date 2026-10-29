
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rsd_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rsd_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.activity_persist import write_state
from src.core.session_activity import (
    EVENT_STOP,
    SessionActivityTracker,
    map_tmux_fallback,
)
from src.core.session_manager import SessionManager
from src.core.session_status import (
    STATUS_DEAD,
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    STATUS_WORKING,
    derive_read_state,
)
from src.core.session_status_seed import StatusSeed, display_state
from src.core.session_status_seed_records import TAIL_AT_REST, TranscriptRest
from src.core.session_transcript_status import (
    RUNG_TURN_END_SEEN,
    resolve_transcript_status,
)
from src.models import Session, SessionStatus




def test_the_derivation_runs_in_both_directions():
    assert derive_read_state(STATUS_FINISHED_UNREAD, unread=False) == STATUS_IDLE
    assert derive_read_state(STATUS_IDLE, unread=True) == STATUS_FINISHED_UNREAD
    assert derive_read_state(STATUS_IDLE, unread=False) == STATUS_IDLE
    assert (
        derive_read_state(STATUS_FINISHED_UNREAD, unread=True)
        == STATUS_FINISHED_UNREAD
    )


def test_it_is_idempotent_so_every_path_may_apply_it():
    for state in (STATUS_IDLE, STATUS_FINISHED_UNREAD):
        for flag in (True, False):
            once = derive_read_state(state, unread=flag)
            assert derive_read_state(once, unread=flag) == once


def test_it_touches_nothing_outside_the_resting_pair():
    for state in (
        STATUS_WORKING,
        STATUS_DEAD,
        STATUS_UNKNOWN,
        STATUS_RUNNING,
        "question",
        "notice",
        "working_subagent",
        None,
    ):
        assert derive_read_state(state, unread=True) == state
        assert derive_read_state(state, unread=False) == state




def _at_rest(*, unread: bool) -> str:
    from src.core.attention.display import to_display
    from src.core.attention.evidence import STATE_DONE_IDLE, AttentionVerdict

    return to_display(
        AttentionVerdict(
            state=STATE_DONE_IDLE,
            reason="test",
            tier="transcript",
            detail="measured at rest",
        ),
        unread=unread,
        tmux_status=STATUS_IDLE,
    )


def test_a_finished_turn_with_the_flag_set_reads_finished_unread():
    assert _at_rest(unread=True) == STATUS_FINISHED_UNREAD


def test_the_same_finished_turn_with_the_flag_clear_reads_idle():
    assert _at_rest(unread=False) == STATUS_IDLE


def test_a_clear_flag_never_answers_finished_unread():
    assert _at_rest(unread=False) != STATUS_FINISHED_UNREAD


def test_derive_read_state_is_the_only_thing_that_splits_the_pair():
    assert derive_read_state(STATUS_IDLE, unread=True) == STATUS_FINISHED_UNREAD
    assert derive_read_state(STATUS_IDLE, unread=False) == STATUS_IDLE
    assert _at_rest(unread=True) == derive_read_state(STATUS_IDLE, unread=True)
    assert _at_rest(unread=False) == derive_read_state(STATUS_IDLE, unread=False)


def test_a_dead_pane_is_dead_whatever_the_flag_says():
    assert map_tmux_fallback(STATUS_DEAD, unread=True) == STATUS_DEAD
    assert map_tmux_fallback(STATUS_DEAD, unread=False) == STATUS_DEAD
    assert derive_read_state(STATUS_DEAD, unread=True) == STATUS_DEAD




def test_tmux_fallback_derives_both_ways():
    assert map_tmux_fallback(STATUS_IDLE, unread=True) == STATUS_FINISHED_UNREAD
    assert map_tmux_fallback(STATUS_IDLE, unread=False) == STATUS_IDLE


def test_tmux_fallback_still_refuses_to_claim_rest_it_did_not_measure():
    assert map_tmux_fallback(STATUS_RUNNING, unread=True) == STATUS_UNKNOWN
    assert map_tmux_fallback(STATUS_DEAD, unread=True) == STATUS_DEAD




def test_seed_a_stored_finished_unread_renders_idle_once_the_flag_clears():
    seed = StatusSeed(state=STATUS_FINISHED_UNREAD, at=None, rung="row")
    assert display_state(seed, unread=False) == STATUS_IDLE
    assert display_state(seed, unread=True) == STATUS_FINISHED_UNREAD


def test_seed_a_stored_idle_renders_finished_unread_when_the_flag_is_set():
    seed = StatusSeed(state=STATUS_IDLE, at=None, rung="row")
    assert display_state(seed, unread=True) == STATUS_FINISHED_UNREAD
    assert display_state(seed, unread=False) == STATUS_IDLE


def test_seed_a_refusal_still_renders_nothing():
    assert display_state(StatusSeed(), unread=True) is None


def test_seed_an_expired_working_claim_is_still_refused():
    now = datetime.now(timezone.utc)
    seed = StatusSeed(
        state=STATUS_WORKING,
        rung="transcript",
        expires_at=now - timedelta(seconds=1),
    )
    assert display_state(seed, unread=True, now=now) is None




def _rest_tail(at: datetime) -> TranscriptRest:
    return TranscriptRest(TAIL_AT_REST, at=at, detail="a turn ended")


def test_transcript_rung_three_follows_the_flag_in_both_directions():
    now = datetime.now(timezone.utc)
    ended = now - timedelta(hours=3)
    tail = _rest_tail(ended)

    read = resolve_transcript_status(
        mtime=ended,
        tail=tail,
        last_turn_end_seen=ended,
        unread=False,
        now=now,
    )
    assert read.rung == RUNG_TURN_END_SEEN
    assert read.state == STATUS_IDLE

    unread = resolve_transcript_status(
        mtime=ended,
        tail=tail,
        last_turn_end_seen=ended,
        unread=True,
        now=now,
    )
    assert unread.rung == RUNG_TURN_END_SEEN
    assert unread.state == STATUS_FINISHED_UNREAD


def test_transcript_rung_two_still_claims_the_turn_it_just_measured():
    now = datetime.now(timezone.utc)
    older = now - timedelta(hours=2)
    newer = now - timedelta(minutes=30)

    status = resolve_transcript_status(
        mtime=newer,
        tail=_rest_tail(newer),
        last_turn_end_seen=older,
        unread=False,
        now=now,
    )
    assert status.state == STATUS_FINISHED_UNREAD
    assert status.claim_turn_end_at == newer




class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path, port: int = 5001):
        self._pin_path = pin_path
        self._log_dir = log_dir
        self.port = port

    def get_pinned_themes_path(self) -> Path:
        return self._pin_path

    def get_unread_state_path(self) -> Path:
        return self._pin_path.parent / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._log_dir)

    def get_session_metadata_path(self) -> Path:
        return self._log_dir / "session_metadata.json"


class _FakeBackend:

    def __init__(self, tmux_session: str):
        self.tmux_session = tmux_session

    def is_alive(self) -> bool:
        return True


def _resting_evidence(now: datetime) -> tuple:
    from src.core.attention.registry_read import (
        REG_IDLE,
        REG_OK,
        RegistryRecord,
    )
    from src.core.attention.transcript_facts import (
        FACTS_FOUND,
        TranscriptFacts,
    )

    ended = now - timedelta(seconds=30)
    return (
        RegistryRecord(
            verdict=REG_OK,
            status=REG_IDLE,
            waiting_for=None,
            pid=4321,
            session_uuid=None,
            tmux_name="cloude_daily-bulletin",
            cwd=None,
            status_updated_at=ended,
            started_at=ended - timedelta(minutes=5),
            version=(2, 1, 266),
            detail="fixture",
        ),
        TranscriptFacts(
            verdict=FACTS_FOUND,
            pending_background_agents=0,
            pending_field_present=True,
            turn_end_at=ended,
            newest_assistant_at=ended - timedelta(seconds=1),
            newest_append_at=ended,
            detail="fixture",
        ),
    )


def _manager_with_row_state(monkeypatch, tmp_path: Path, stored: str) -> SessionManager:
    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json", log_dir=tmp_path / "logs"
    )
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    mgr = SessionManager()
    mgr._registry.sessions["ses1"] = Session(
        id="ses1",
        pty_pid=None,
        working_dir=str(tmp_path),
        status=SessionStatus.RUNNING,
        tmux_session="cloude_daily-bulletin",
    )
    mgr._registry.backends["ses1"] = _FakeBackend("cloude_daily-bulletin")
    mgr._registry.subscribers.setdefault("ses1", [])
    monkeypatch.setattr(
        mgr,
        "_build_tmux_status_map",
        lambda: {"cloude_daily-bulletin": {"status": STATUS_IDLE}},
    )
    from types import SimpleNamespace
    from src.core.attention.evidence import AttentionVerdict
    registry, _transcript = _resting_evidence(datetime.now(timezone.utc))
    observation = SimpleNamespace(
        verdict=AttentionVerdict("done_idle", "turn_ended", "registry"),
        evidence=SimpleNamespace(registry=registry),
    )
    mgr._attention_watcher = SimpleNamespace(
        observation_for=lambda *args, **kw: observation,
    )
    return mgr


def test_a_row_recording_finished_unread_reads_idle_once_the_tab_is_opened(
    monkeypatch, tmp_path
):
    mgr = _manager_with_row_state(monkeypatch, tmp_path, STATUS_FINISHED_UNREAD)

    mgr.set_manual_unread("cloude_daily-bulletin", True)
    info = mgr._session_info_for("ses1")
    assert info.unread is True
    assert info.activity_status == STATUS_FINISHED_UNREAD

    mgr.mark_session_viewed("ses1")
    info = mgr._session_info_for("ses1")
    assert info.unread is False
    assert info.activity_status == STATUS_IDLE, (
        "the row still records finished_unread; the flag is what decides"
    )


def test_the_flag_transitions_are_idempotent_set_view_set_view(
    monkeypatch, tmp_path
):
    mgr = _manager_with_row_state(monkeypatch, tmp_path, STATUS_FINISHED_UNREAD)
    name = "cloude_daily-bulletin"

    for _ in range(2):
        mgr.set_manual_unread(name, True)
        info = mgr._session_info_for("ses1")
        assert (info.unread, info.activity_status) == (True, STATUS_FINISHED_UNREAD)

    for _ in range(2):
        mgr.mark_session_viewed("ses1")
        info = mgr._session_info_for("ses1")
        assert (info.unread, info.activity_status) == (False, STATUS_IDLE)

    for _ in range(2):
        mgr.set_manual_unread(name, True)
        info = mgr._session_info_for("ses1")
        assert (info.unread, info.activity_status) == (True, STATUS_FINISHED_UNREAD)

    for _ in range(2):
        mgr.set_manual_unread(name, False)
        info = mgr._session_info_for("ses1")
        assert (info.unread, info.activity_status) == (False, STATUS_IDLE)


def test_a_row_recording_idle_reads_finished_unread_when_the_flag_is_set(
    monkeypatch, tmp_path
):
    mgr = _manager_with_row_state(monkeypatch, tmp_path, STATUS_IDLE)
    mgr.set_manual_unread("cloude_daily-bulletin", True)
    info = mgr._session_info_for("ses1")
    assert info.activity_status == STATUS_FINISHED_UNREAD




class _RecordingConn:

    def __init__(self):
        self.params = None

    def execute(self, sql, params=()):
        if sql.startswith("PRAGMA"):
            return iter(())
        self.params = params

        class _Cur:
            rowcount = 1

        return _Cur()


def test_the_row_stores_the_base_state_never_the_read_verdict():
    conn = _RecordingConn()
    assert write_state(conn, "cloude_x", STATUS_FINISHED_UNREAD, 1757000000) is True
    assert conn.params[0] == STATUS_IDLE


def test_the_writer_leaves_every_other_state_alone():
    for state in (STATUS_WORKING, "question", "notice", STATUS_IDLE):
        conn = _RecordingConn()
        write_state(conn, "cloude_x", state, 1757000000)
        assert conn.params[0] == state


def test_the_writer_still_refuses_a_write_with_no_epoch():
    conn = _RecordingConn()
    assert write_state(conn, "cloude_x", STATUS_FINISHED_UNREAD, None) is False
    assert conn.params is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

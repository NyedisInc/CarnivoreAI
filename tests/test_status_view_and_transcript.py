
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core.session_manager import SessionManager
from src.models import Session, SessionStatus
from src.core.session_activity import (
    WORKING_HEARTBEAT_TIMEOUT_SECONDS,
    SessionActivitySignal,
    SessionActivityTracker,
)
from src.core.attention.registry_read import (
    REG_BUSY,
    REG_OK,
    RegistryRecord,
)
from src.core.session_status import (
    STATUS_DEAD,
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_NOTICE,
    STATUS_QUESTION,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    STATUS_WORKING,
)
from src.core.session_status_seed import StatusSeed, display_state
from src.core.session_status_seed_records import (
    TAIL_ABSENT,
    TAIL_AT_REST,
    TAIL_IN_FLIGHT,
    TAIL_NO_MARKER,
    TAIL_UNREADABLE,
    TranscriptRest,
)
from src.core.session_status_source import (
    ALL_STATUS_SOURCES,
    STATUS_SOURCE_NONE,
    STATUS_SOURCE_PANE,
    STATUS_SOURCE_REGISTRY,
    STATUS_SOURCE_SEED_ROW,
    STATUS_SOURCE_TMUX,
    STATUS_SOURCE_TRANSCRIPT,
    source_for_seed_rung,
)
from src.core.session_transcript_status import (
    RUNG_MTIME,
    RUNG_NO_TRANSCRIPT,
    RUNG_STALE_IN_FLIGHT,
    RUNG_TURN_END_NEW,
    RUNG_TURN_END_SEEN,
    TranscriptStatus,
    resolve_transcript_status,
)
from src.core.session_transcript_status_read import (
    TranscriptReading,
    TranscriptTurnLedger,
    ledger_for,
    read_transcript_signal,
    transcript_status_for,
)



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


def _bare_manager(monkeypatch, tmp_path: Path, port: int = 5001) -> SessionManager:
    stub = _StubSettings(
        pin_path=tmp_path / "pinned_themes.json",
        log_dir=tmp_path / "logs",
        port=port,
    )
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()


def _register_session(
    mgr: SessionManager, sid: str, tmux_name: str, working_dir: Path
) -> Session:
    sess = Session(
        id=sid,
        pty_pid=None,
        working_dir=str(working_dir),
        status=SessionStatus.RUNNING,
        tmux_session=tmux_name,
    )
    mgr._registry.sessions[sid] = sess
    mgr._registry.backends[sid] = _FakeBackend(tmux_name)
    mgr._registry.subscribers.setdefault(sid, [])
    return sess


NOW = datetime(2026, 9, 9, 14, 0, 0, tzinfo=timezone.utc)


def _open_claims(
    tracker: SessionActivityTracker,
    session_id: str,
    *,
    notice: bool = False,
    permission: bool = False,
    at: datetime = NOW,
) -> None:
    tracker._signals[session_id] = SessionActivitySignal(
        permission_open=permission,
        permission_opened_at=at if permission else None,
        notice_open=notice,
    )




def test_clear_notice_drops_an_open_notification():
    tracker = SessionActivityTracker()
    _open_claims(tracker, "s1", notice=True)

    assert tracker.clear_notice("s1") is True
    assert tracker._signals["s1"].notice_open is False


def test_clear_notice_is_idempotent():
    tracker = SessionActivityTracker()
    _open_claims(tracker, "s1", notice=True)
    assert tracker.clear_notice("s1") is True
    assert tracker.clear_notice("s1") is False
    assert tracker.clear_notice("never-seen") is False


def test_clear_notice_never_clears_a_permission():
    tracker = SessionActivityTracker()
    _open_claims(tracker, "s1", notice=True, permission=True)

    tracker.clear_notice("s1")

    assert tracker._signals["s1"].notice_open is False
    assert tracker._signals["s1"].permission_open is True
    assert tracker.permission_open_since("s1") == NOW


def test_a_websocket_bind_clears_the_notice_and_the_unread_flag(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_session(mgr, "ses1", "cloude_proj", tmp_path)
    _open_claims(mgr._activity_tracker, "ses1", notice=True)
    mgr.set_manual_unread("cloude_proj", True)
    assert mgr._is_unread("cloude_proj") is True

    mgr.mark_session_viewed("ses1")

    assert mgr._is_unread("cloude_proj") is False
    assert mgr._activity_tracker._signals["ses1"].notice_open is False


def test_a_websocket_bind_clears_a_permission_prompt(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_session(mgr, "ses1", "cloude_proj", tmp_path)
    _open_claims(mgr._activity_tracker, "ses1", permission=True)
    assert mgr._activity_tracker.permission_open_since("ses1") == NOW

    mgr.mark_session_viewed("ses1")

    assert mgr._activity_tracker._signals["ses1"].permission_open is False
    assert mgr._activity_tracker.permission_open_since("ses1") is None


def test_the_manual_mark_read_control_clears_the_notice_too(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_session(mgr, "ses1", "cloude_proj", tmp_path)
    _open_claims(mgr._activity_tracker, "ses1", notice=True)
    mgr.set_manual_unread("cloude_proj", True)

    mgr.set_manual_unread("cloude_proj", False)

    assert mgr._is_unread("cloude_proj") is False
    assert mgr._activity_tracker._signals["ses1"].notice_open is False


def test_marking_a_session_unread_does_not_clear_its_notice(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_session(mgr, "ses1", "cloude_proj", tmp_path)
    _open_claims(mgr._activity_tracker, "ses1", notice=True)

    mgr.set_manual_unread("cloude_proj", True)

    assert mgr._activity_tracker._signals["ses1"].notice_open is True




def _rest(at=None):
    return TranscriptRest(TAIL_AT_REST, at=at, detail="at rest")


def test_rung_1_a_fresh_mtime_reads_working_and_carries_an_expiry():
    status = resolve_transcript_status(
        mtime=NOW - timedelta(seconds=5),
        tail=_rest(NOW - timedelta(days=3)),
        last_turn_end_seen=None,
        unread=False,
        now=NOW,
    )
    assert status.state == STATUS_WORKING
    assert status.rung == RUNG_MTIME
    assert status.expires_at == (
        NOW - timedelta(seconds=5)
        + timedelta(seconds=WORKING_HEARTBEAT_TIMEOUT_SECONDS)
    )


def test_rung_1_refuses_an_mtime_from_the_future():
    status = resolve_transcript_status(
        mtime=NOW + timedelta(minutes=5),
        tail=_rest(NOW - timedelta(days=3)),
        last_turn_end_seen=NOW - timedelta(days=4),
        unread=False,
        now=NOW,
    )
    assert status.state != STATUS_WORKING


def test_rung_1_expires_exactly_at_the_heartbeat_window():
    edge = NOW - timedelta(seconds=WORKING_HEARTBEAT_TIMEOUT_SECONDS)
    just_past = edge - timedelta(seconds=1)
    assert resolve_transcript_status(
        mtime=edge, tail=None, last_turn_end_seen=None, unread=False, now=NOW,
    ).state == STATUS_WORKING
    assert resolve_transcript_status(
        mtime=just_past, tail=None, last_turn_end_seen=None, unread=False,
        now=NOW,
    ).state is None


def test_rung_2_a_newer_turn_end_finishes_unread_and_owes_a_claim():
    seen = NOW - timedelta(hours=2)
    fresh = NOW - timedelta(minutes=30)
    status = resolve_transcript_status(
        mtime=NOW - timedelta(minutes=30),
        tail=_rest(fresh),
        last_turn_end_seen=seen,
        unread=False,
        now=NOW,
    )
    assert status.state == STATUS_FINISHED_UNREAD
    assert status.rung == RUNG_TURN_END_NEW
    assert status.claim_turn_end_at == fresh


def test_rung_2_never_claims_on_a_first_sighting():
    status = resolve_transcript_status(
        mtime=NOW - timedelta(days=40),
        tail=_rest(NOW - timedelta(days=40)),
        last_turn_end_seen=None,
        unread=False,
        now=NOW,
    )
    assert status.claim_turn_end_at is None
    assert status.rung == RUNG_TURN_END_SEEN
    assert status.state == STATUS_IDLE


def test_rung_2_never_claims_on_an_undated_turn_end():
    status = resolve_transcript_status(
        mtime=NOW - timedelta(days=1),
        tail=_rest(None),
        last_turn_end_seen=NOW - timedelta(days=9),
        unread=False,
        now=NOW,
    )
    assert status.claim_turn_end_at is None
    assert status.state == STATUS_IDLE


def test_rung_2_never_relights_an_older_turn_end():
    status = resolve_transcript_status(
        mtime=NOW - timedelta(days=1),
        tail=_rest(NOW - timedelta(days=5)),
        last_turn_end_seen=NOW - timedelta(days=2),
        unread=False,
        now=NOW,
    )
    assert status.claim_turn_end_at is None
    assert status.state == STATUS_IDLE


def test_rung_3_reads_the_unread_flag_a_view_left_behind():
    seen = NOW - timedelta(hours=6)
    common = dict(
        mtime=NOW - timedelta(hours=6),
        tail=_rest(seen),
        last_turn_end_seen=seen,
        now=NOW,
    )
    assert resolve_transcript_status(unread=True, **common).state == (
        STATUS_FINISHED_UNREAD
    )
    assert resolve_transcript_status(unread=False, **common).state == STATUS_IDLE


@pytest.mark.parametrize("verdict", [TAIL_IN_FLIGHT, TAIL_NO_MARKER])
def test_rung_4_a_stale_in_flight_transcript_claims_nothing(verdict):
    status = resolve_transcript_status(
        mtime=NOW - timedelta(days=2),
        tail=TranscriptRest(verdict, detail="x"),
        last_turn_end_seen=None,
        unread=False,
        now=NOW,
    )
    assert status.state is None
    assert status.rung == RUNG_STALE_IN_FLIGHT


@pytest.mark.parametrize("verdict", [TAIL_ABSENT, TAIL_UNREADABLE])
def test_rung_5_no_transcript_claims_nothing(verdict):
    status = resolve_transcript_status(
        mtime=None,
        tail=TranscriptRest(verdict, detail="x"),
        last_turn_end_seen=None,
        unread=False,
        now=NOW,
    )
    assert status.state is None


def test_the_ladder_refuses_more_often_than_it_answers_on_junk():
    refusals = 0
    for tail in (
        None,
        TranscriptRest(TAIL_ABSENT, detail="x"),
        TranscriptRest(TAIL_UNREADABLE, detail="x"),
        TranscriptRest(TAIL_IN_FLIGHT, detail="x"),
        TranscriptRest(TAIL_NO_MARKER, detail="x"),
    ):
        status = resolve_transcript_status(
            mtime=None, tail=tail, last_turn_end_seen=None, unread=False,
            now=NOW,
        )
        refusals += 0 if status.answers else 1
    assert refusals == 5




def test_the_ledger_baselines_then_notices_exactly_one_new_turn():
    older = NOW - timedelta(hours=3)
    newer = NOW - timedelta(hours=1)
    ledger = TranscriptTurnLedger()
    assert ledger.observe("k", older) is False
    assert ledger.observe("k", newer) is True
    assert ledger.observe("k", newer) is False
    assert ledger.observe("k", older) is False
    assert ledger.newest_seen("k") == newer


def test_the_ledger_refuses_an_undated_or_unkeyed_observation():
    ledger = TranscriptTurnLedger()
    assert ledger.observe("k", None) is False
    assert ledger.observe("", NOW) is False


class _RecordingUnreadStore:

    def __init__(self) -> None:
        self.writes: list[tuple] = []

    def set_flag(self, tmux_name, field_name, value, epoch=None):
        self.writes.append((tmux_name, field_name, value, epoch))


class _FakeManager:

    def __init__(self) -> None:
        self._unread_store = _RecordingUnreadStore()


def test_a_new_turn_end_sets_unread_exactly_once_across_repeated_passes():
    mgr = _FakeManager()
    baseline = TranscriptReading(
        mtime=NOW - timedelta(days=1), tail=_rest(NOW - timedelta(days=1))
    )
    newer = TranscriptReading(
        mtime=NOW - timedelta(minutes=30), tail=_rest(NOW - timedelta(minutes=30))
    )
    common = dict(session_id="s1", tmux_name="cloude_x", epoch=1757000000,
                  unread=False, now=NOW)

    transcript_status_for(mgr, reading=baseline, **common)
    assert mgr._unread_store.writes == []

    first = transcript_status_for(mgr, reading=newer, **common)
    assert first.state == STATUS_FINISHED_UNREAD
    assert mgr._unread_store.writes == [
        ("cloude_x", "auto", True, 1757000000)
    ]

    for _ in range(5):
        transcript_status_for(mgr, reading=newer, **common)
    assert len(mgr._unread_store.writes) == 1


def test_the_working_rung_never_moves_the_turn_baseline():
    mgr = _FakeManager()
    turn_at = NOW - timedelta(hours=4)
    transcript_status_for(
        mgr, session_id="s1", tmux_name="cloude_x", epoch=1,
        reading=TranscriptReading(mtime=turn_at, tail=_rest(turn_at)),
        unread=False, now=NOW,
    )
    before = ledger_for(mgr).newest_seen("cloude_x@1")

    transcript_status_for(
        mgr, session_id="s1", tmux_name="cloude_x", epoch=1,
        reading=TranscriptReading(
            mtime=NOW - timedelta(seconds=5), tail=_rest(turn_at)
        ),
        unread=False, now=NOW,
    )
    assert ledger_for(mgr).newest_seen("cloude_x@1") == before




def _write_transcript(corpus_root: Path, working_dir: str, uuid: str,
                      records: list, age_seconds: int = 3600) -> Path:
    from src.core.claude_transcript_correlate import slugify_project_dir

    directory = corpus_root / slugify_project_dir(working_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid}.jsonl"
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    if age_seconds:
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
    return path


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    home = tmp_path / "home"
    projects = home / ".claude" / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return projects


def test_the_reader_takes_both_measurements_off_one_real_file(
    corpus, tmp_path
):
    uuid = "c50ad4f7-9571-4b78-81f4-ac0c83fe96b8"
    wd = str(tmp_path / "proj")
    _write_transcript(
        corpus, wd, uuid,
        [{"type": "system", "subtype": "turn_duration",
          "timestamp": "2026-09-04T19:39:04.864Z", "isSidechain": False}],
        age_seconds=0,
    )
    reading = read_transcript_signal(uuid, wd)
    assert reading.tail.verdict == TAIL_AT_REST
    assert reading.mtime is not None
    assert (datetime.now(timezone.utc) - reading.mtime) < timedelta(minutes=1)


def test_a_missing_transcript_reads_absent_with_no_mtime(corpus, tmp_path):
    reading = read_transcript_signal(
        "00000000-0000-4000-8000-000000000000", str(tmp_path / "nope")
    )
    assert reading.mtime is None
    assert reading.tail.verdict in (TAIL_ABSENT, TAIL_UNREADABLE)


def test_no_uuid_is_a_named_refusal_not_a_crash():
    reading = read_transcript_signal(None, None)
    assert reading.mtime is None
    assert reading.tail.verdict == TAIL_ABSENT




REGISTRY_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)


def _registry_index(monkeypatch, records: dict) -> None:
    monkeypatch.setattr(
        "src.core.attention.registry_read.read_registry_index",
        lambda *a, **k: records,
    )


def _busy_record(tmux_name: str) -> "RegistryRecord":
    return RegistryRecord(
        verdict=REG_OK,
        status=REG_BUSY,
        waiting_for=None,
        pid=4321,
        session_uuid=None,
        tmux_name=tmux_name,
        cwd=None,
        status_updated_at=REGISTRY_NOW,
        started_at=REGISTRY_NOW,
        version=(2, 1, 266),
        detail="fixture",
    )


@pytest.mark.asyncio
async def test_a_live_registry_record_decides_the_row(monkeypatch, tmp_path):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_session(mgr, "ses1", "cloude_proj", tmp_path)
    _registry_index(monkeypatch, {"cloude_proj": _busy_record("cloude_proj")})
    monkeypatch.setattr(mgr, "_build_tmux_status_map", lambda: {
        "cloude_proj": {"status": STATUS_RUNNING}
    })

    infos = await mgr.list_session_infos()

    assert infos[0].activity_status == STATUS_WORKING
    assert infos[0].status_source == STATUS_SOURCE_REGISTRY


@pytest.mark.asyncio
async def test_a_row_with_no_registry_record_paints_unknown_never_idle(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_session(mgr, "ses1", "cloude_proj", tmp_path)
    _registry_index(monkeypatch, {})
    monkeypatch.setattr(mgr, "_build_tmux_status_map", lambda: {
        "cloude_proj": {"status": STATUS_IDLE}
    })

    infos = await mgr.list_session_infos()

    assert infos[0].activity_status == STATUS_UNKNOWN
    assert infos[0].activity_status != STATUS_IDLE
    assert infos[0].status_source == STATUS_SOURCE_REGISTRY


@pytest.mark.asyncio
async def test_an_observed_row_beats_the_live_fallback(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from src.core.attention.evidence import (
        AttentionVerdict,
        REASON_TURN_ENDED,
        STATE_DONE_IDLE,
        TIER_TRANSCRIPT,
    )

    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_session(mgr, "ses1", "cloude_proj", tmp_path)
    _registry_index(monkeypatch, {"cloude_proj": _busy_record("cloude_proj")})
    monkeypatch.setattr(mgr, "_build_tmux_status_map", lambda: {
        "cloude_proj": {"status": STATUS_RUNNING}
    })
    mgr._attention_watcher = SimpleNamespace(
        observation_for=lambda *args, **kwargs: SimpleNamespace(
            verdict=AttentionVerdict(
                STATE_DONE_IDLE, REASON_TURN_ENDED, TIER_TRANSCRIPT
            ),
            evidence=SimpleNamespace(registry=_busy_record("cloude_proj")),
        )
    )

    infos = await mgr.list_session_infos()

    assert infos[0].activity_status == STATUS_IDLE
    assert infos[0].status_source == STATUS_SOURCE_TRANSCRIPT, (
        "the listing re-resolved a row the watcher had already observed"
    )


@pytest.mark.asyncio
async def test_a_codex_row_with_no_observation_is_read_by_the_codex_reader(
    monkeypatch, tmp_path
):
    from src.core.attention.codex_reader import (
        CODEX_RECORD_REST,
        CodexEvidence,
        CodexRecordFacts,
    )

    mgr = _bare_manager(monkeypatch, tmp_path)
    sess = _register_session(mgr, "ses1", "cloude_proj", tmp_path)
    sess.agent_type = "codex"
    _registry_index(monkeypatch, {"cloude_proj": _busy_record("cloude_proj")})
    monkeypatch.setattr(mgr, "_build_tmux_status_map", lambda: {
        "cloude_proj": {"status": STATUS_RUNNING}
    })
    monkeypatch.setattr(
        "src.core.attention.codex_gather.gather_codex_evidence",
        lambda *args, **kwargs: CodexEvidence(
            record=CodexRecordFacts(verdict=CODEX_RECORD_REST)
        ),
    )

    infos = await mgr.list_session_infos()

    assert infos[0].agent_family == "codex"
    assert infos[0].activity_status == STATUS_IDLE, (
        "claude's registry decided a codex row"
    )


@pytest.mark.asyncio
async def test_a_measured_pane_death_outranks_a_live_registry_record(
    monkeypatch, tmp_path
):
    mgr = _bare_manager(monkeypatch, tmp_path)
    _register_session(mgr, "ses1", "cloude_proj", tmp_path)
    _registry_index(monkeypatch, {"cloude_proj": _busy_record("cloude_proj")})
    monkeypatch.setattr(mgr, "_build_tmux_status_map", lambda: {
        "cloude_proj": {"status": STATUS_DEAD}
    })

    infos = await mgr.list_session_infos()

    assert [i.activity_status for i in infos] != [STATUS_WORKING]
    assert all(i.activity_status != STATUS_WORKING for i in infos)


def test_the_dead_pane_verdict_paints_dead_and_never_borrows_an_idle():
    from src.core.attention.display import to_display
    from src.core.attention.evidence import (
        REASON_PANE_DEAD,
        REASON_REGISTRY_ABSENT,
        STATE_UNKNOWN,
        TIER_REGISTRY,
        TIER_TMUX,
        AttentionVerdict,
    )
    from src.core.session_status import STATUS_DEAD as DEAD

    dead = AttentionVerdict(
        state=STATE_UNKNOWN, reason=REASON_PANE_DEAD, tier=TIER_TMUX
    )
    assert to_display(dead, unread=False, tmux_status=STATUS_RUNNING) == DEAD

    nothing = AttentionVerdict(
        state=STATE_UNKNOWN, reason=REASON_REGISTRY_ABSENT, tier=TIER_REGISTRY
    )
    assert (
        to_display(nothing, unread=False, tmux_status=STATUS_IDLE)
        == STATUS_UNKNOWN
    ), "an unmeasured session must never borrow tmux's idle"




def test_a_cached_working_seed_stops_rendering_once_its_window_closes():
    seed = StatusSeed(
        state=STATUS_WORKING,
        at=NOW,
        expires_at=NOW + timedelta(seconds=WORKING_HEARTBEAT_TIMEOUT_SECONDS),
    )
    assert display_state(seed, now=NOW) == STATUS_WORKING
    assert display_state(seed, now=NOW + timedelta(seconds=119)) == STATUS_WORKING
    assert display_state(seed, now=NOW + timedelta(seconds=121)) is None


def test_a_resting_seed_carries_no_expiry_and_never_rots():
    seed = StatusSeed(state=STATUS_IDLE, at=NOW - timedelta(days=60))
    assert seed.expires_at is None
    assert display_state(seed, now=NOW + timedelta(days=365)) == STATUS_IDLE




def test_every_source_is_one_of_the_six_named_values():
    assert ALL_STATUS_SOURCES == {
        STATUS_SOURCE_REGISTRY,
        STATUS_SOURCE_PANE,
        STATUS_SOURCE_TRANSCRIPT,
        STATUS_SOURCE_SEED_ROW,
        STATUS_SOURCE_TMUX,
        STATUS_SOURCE_NONE,
    }
    assert "hook" not in ALL_STATUS_SOURCES


def test_every_tier_names_a_source_and_an_unknown_tier_names_none():
    from src.core.attention.display import status_source_for
    from src.core.attention.evidence import (
        REASON_TURN_ENDED,
        STATE_DONE_IDLE,
        TIER_NONE,
        TIER_PANE,
        TIER_REGISTRY,
        TIER_TMUX,
        TIER_TRANSCRIPT,
        AttentionVerdict,
    )

    def _source(tier: str) -> str:
        return status_source_for(
            AttentionVerdict(
                state=STATE_DONE_IDLE, reason=REASON_TURN_ENDED, tier=tier
            )
        )

    assert _source(TIER_REGISTRY) == STATUS_SOURCE_REGISTRY
    assert _source(TIER_TRANSCRIPT) == STATUS_SOURCE_TRANSCRIPT
    assert _source(TIER_PANE) == STATUS_SOURCE_PANE
    assert _source(TIER_TMUX) == STATUS_SOURCE_TMUX
    assert _source(TIER_NONE) == STATUS_SOURCE_NONE
    assert _source("a tier nobody defined") == STATUS_SOURCE_NONE
    for tier in (TIER_REGISTRY, TIER_TRANSCRIPT, TIER_PANE, TIER_TMUX, TIER_NONE):
        assert _source(tier) in ALL_STATUS_SOURCES


def test_a_seed_rung_maps_to_exactly_one_source():
    from src.core.session_status_seed import (
        SEED_RUNG_NONE,
        SEED_RUNG_ROW,
        SEED_RUNG_TRANSCRIPT,
    )

    assert source_for_seed_rung(SEED_RUNG_ROW) == STATUS_SOURCE_SEED_ROW
    assert source_for_seed_rung(SEED_RUNG_TRANSCRIPT) == STATUS_SOURCE_TRANSCRIPT
    assert source_for_seed_rung(SEED_RUNG_NONE) == STATUS_SOURCE_NONE
    assert source_for_seed_rung("a rung nobody defined") == STATUS_SOURCE_NONE


def test_the_wrapper_carries_status_source_and_defaults_to_none():
    from src.models import SessionInfo

    assert "status_source" in SessionInfo.model_fields
    assert SessionInfo.model_fields["status_source"].default == (
        STATUS_SOURCE_NONE
    )


def test_a_status_source_is_never_reported_for_an_expired_claim():
    status = TranscriptStatus(rung=RUNG_NO_TRANSCRIPT, detail="x")
    assert status.answers is False

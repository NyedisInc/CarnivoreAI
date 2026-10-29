
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import tempfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import structlog

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_sss_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_sss_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.activity_persist import utc_now_iso, write_state
from src.core.claude_transcript_correlate import slugify_project_dir
from src.core.db import connect, db_path_for
from src.core.session_status import (
    STATUS_DEAD,
    STATUS_FINISHED_UNREAD,
    STATUS_IDLE,
    STATUS_QUESTION,
    STATUS_UNKNOWN,
    STATUS_WORKING,
)
from src.core.session_status_seed import (
    SEED_REFRESH_INTERVAL_SECONDS,
    SEED_RUNG_NONE,
    SEED_RUNG_ROW,
    SEED_RUNG_TRANSCRIPT,
    TAIL_ABSENT,
    TAIL_AT_REST,
    TAIL_IN_FLIGHT,
    TAIL_NO_MARKER,
    TAIL_UNREADABLE,
    StatusSeed,
    TranscriptRest,
    classify_record,
    classify_tail_records,
    display_state,
    resolve_status_seed,
)
from src.core.session_status_seed_read import (
    derive_seed,
    read_instance_row,
    read_transcript_rest,
    seed_live_sessions,
    seeded_status,
    seeds_for,
)
from src.core.session_status_seed_store import SessionStatusSeeds

NOW = datetime(2026, 9, 8, 22, 24, 0, tzinfo=timezone.utc)
UUID = "c2e5255b-bf71-449d-9799-57e5bd0371c1"




def turn_duration(ts="2026-09-04T19:39:04.864Z"):
    return {"type": "system", "subtype": "turn_duration", "timestamp": ts,
            "isSidechain": False}


def stop_hook_summary(ts="2026-09-04T19:39:04.863Z"):
    return {"type": "system", "subtype": "stop_hook_summary", "timestamp": ts,
            "isSidechain": False}


def assistant(stop_reason, ts="2026-09-04T19:38:58.240Z", sidechain=False):
    return {
        "type": "assistant",
        "timestamp": ts,
        "isSidechain": sidechain,
        "message": {"role": "assistant", "stop_reason": stop_reason,
                    "content": [{"type": "text", "text": "hi"}]},
    }


def user_prompt(text="do the thing", ts="2026-09-04T19:38:00.000Z"):
    return {
        "type": "user",
        "timestamp": ts,
        "isSidechain": False,
        "message": {"role": "user", "content": text},
    }


def tool_result(ts="2026-09-04T19:38:26.989Z"):
    return {
        "type": "user",
        "timestamp": ts,
        "isSidechain": False,
        "message": {"role": "user",
                    "content": [{"type": "tool_result", "content": "ok"}]},
    }


def local_command(ts="2026-09-04T22:04:59.794Z"):
    return {"type": "system", "subtype": "local_command", "timestamp": ts,
            "isSidechain": False}


def command_envelope(ts="2026-09-04T22:04:59.792Z"):
    return {
        "type": "user",
        "timestamp": ts,
        "isSidechain": False,
        "message": {"role": "user",
                    "content": "<command-name>/rename</command-name> foo"},
    }


def noise():
    return [
        {"type": "file-history-snapshot"},
        {"type": "attachment", "timestamp": "2026-09-04T19:38:26.999Z"},
        {"type": "queue-operation", "timestamp": "2026-09-04T19:38:27.000Z"},
        {"type": "last-prompt"},
        {"type": "mode"},
        {"type": "custom-title", "customTitle": "x"},
    ]




@pytest.mark.parametrize("closer", [turn_duration(), stop_hook_summary(),
                                    assistant("end_turn"),
                                    assistant("stop_sequence")])
def test_a_tail_that_ends_a_turn_reads_at_rest(closer):
    verdict = classify_tail_records([user_prompt(), closer])
    assert verdict.verdict == TAIL_AT_REST
    assert verdict.at is not None
    assert verdict.at.tzinfo is not None


def test_at_rest_seeds_idle_dated_by_the_record_that_decided_it():
    tail = classify_tail_records([turn_duration("2026-09-04T19:39:04.864Z")])
    seed = resolve_status_seed(row_state=None, row_state_at=None, tail=tail,
                               now=NOW)
    assert seed.state == STATUS_IDLE
    assert seed.rung == SEED_RUNG_TRANSCRIPT
    assert seed.at == datetime(2026, 9, 4, 19, 39, 4, 864000,
                               tzinfo=timezone.utc)


def test_undecidable_noise_after_a_closer_does_not_hide_the_rest():
    records = [user_prompt(), turn_duration()] + noise()
    assert classify_tail_records(records).verdict == TAIL_AT_REST




def test_a_user_prompt_tail_seeds_nothing():
    tail = classify_tail_records([turn_duration(), user_prompt()])
    assert tail.verdict == TAIL_IN_FLIGHT
    seed = resolve_status_seed(row_state=None, row_state_at=None, tail=tail,
                               now=NOW)
    assert seed.state is None
    assert seed.rung == SEED_RUNG_NONE


def test_an_assistant_that_stopped_to_call_a_tool_seeds_nothing():
    tail = classify_tail_records([turn_duration(), assistant("tool_use")])
    assert tail.verdict == TAIL_IN_FLIGHT
    assert resolve_status_seed(row_state=None, row_state_at=None,
                               tail=tail).state is None


def test_a_tool_result_tail_seeds_nothing():
    assert classify_tail_records([tool_result()]).verdict == TAIL_IN_FLIGHT


def test_the_newest_decidable_record_wins():
    records = [turn_duration("2026-09-01T00:00:00Z"),
               user_prompt(ts="2026-09-08T22:00:00Z")]
    assert classify_tail_records(records).verdict == TAIL_IN_FLIGHT


def test_a_subagent_finishing_is_not_the_conversation_finishing():
    records = [user_prompt(), assistant("end_turn", sidechain=True)]
    assert classify_tail_records(records).verdict == TAIL_IN_FLIGHT
    assert classify_record(assistant("end_turn", sidechain=True)) is None


def test_an_empty_window_answers_no_marker_not_at_rest():
    assert classify_tail_records([]).verdict == TAIL_NO_MARKER
    assert classify_tail_records(noise()).verdict == TAIL_NO_MARKER
    assert resolve_status_seed(row_state=None, row_state_at=None,
                               tail=classify_tail_records([])).state is None


def test_an_unreadable_transcript_refuses_rather_than_answering_idle():
    seed = resolve_status_seed(
        row_state=None, row_state_at=None,
        tail=TranscriptRest(TAIL_UNREADABLE, detail="permission denied"),
    )
    assert seed.state is None
    assert TAIL_UNREADABLE in (seed.detail or "")


def test_a_measured_absent_transcript_is_named_apart_from_an_unreadable_one():
    absent = resolve_status_seed(row_state=None, row_state_at=None,
                                 tail=TranscriptRest(TAIL_ABSENT))
    unreadable = resolve_status_seed(row_state=None, row_state_at=None,
                                     tail=TranscriptRest(TAIL_UNREADABLE))
    assert absent.state is None and unreadable.state is None
    assert absent.detail != unreadable.detail


def test_a_transcript_that_was_not_consulted_is_not_an_absent_one():
    seed = resolve_status_seed(row_state=None, row_state_at=None, tail=None)
    assert seed.state is None
    assert "not consulted" in (seed.detail or "")




def test_a_slash_command_is_not_a_prompt_and_the_walk_continues_past_it():
    records = [assistant("end_turn", ts="2026-09-04T22:04:00Z"),
               command_envelope(), local_command()]
    assert classify_tail_records(records).verdict == TAIL_AT_REST


def test_the_envelope_is_undecidable_and_never_rest_on_its_own():
    assert classify_record(command_envelope()) is None
    assert classify_record(local_command()) is None
    assert classify_tail_records(
        [command_envelope(), local_command()]
    ).verdict == TAIL_NO_MARKER


def test_a_prompt_that_merely_mentions_the_tag_is_still_a_prompt():
    quoting = user_prompt(text="why does <command-name> break the ladder?")
    assert classify_record(quoting) is False




def test_a_fresh_row_state_seeds_itself():
    stamp = (NOW - timedelta(seconds=30)).isoformat()
    seed = resolve_status_seed(
        row_state=STATUS_QUESTION, row_state_at=stamp,
        tail=classify_tail_records([turn_duration()]), now=NOW,
    )
    assert seed.state == STATUS_QUESTION
    assert seed.rung == SEED_RUNG_ROW


def test_a_stale_working_row_does_not_seed_working():
    stamp = (NOW - timedelta(hours=6)).isoformat()
    seed = resolve_status_seed(row_state=STATUS_WORKING, row_state_at=stamp,
                               tail=None, now=NOW)
    assert seed.state is None

    seeded = resolve_status_seed(
        row_state=STATUS_WORKING, row_state_at=stamp,
        tail=classify_tail_records([turn_duration()]), now=NOW,
    )
    assert seeded.state == STATUS_IDLE
    assert seeded.rung == SEED_RUNG_TRANSCRIPT


@pytest.mark.parametrize("resting", [STATUS_IDLE, STATUS_FINISHED_UNREAD])
def test_a_stale_resting_row_still_seeds_itself(resting):
    stamp = (NOW - timedelta(days=4)).isoformat()
    seed = resolve_status_seed(row_state=resting, row_state_at=stamp,
                               tail=None, now=NOW)
    assert seed.state == resting
    assert seed.rung == SEED_RUNG_ROW


@pytest.mark.parametrize("refused", [STATUS_DEAD, STATUS_UNKNOWN, None, ""])
def test_a_row_may_never_seed_dead_or_unknown(refused):
    seed = resolve_status_seed(row_state=refused, row_state_at=utc_now_iso(),
                               tail=None, now=NOW)
    assert seed.state is None


def test_a_perishable_state_with_no_readable_date_is_refused():
    seed = resolve_status_seed(row_state=STATUS_WORKING,
                               row_state_at="not a timestamp", tail=None,
                               now=NOW)
    assert seed.state is None




def test_an_unread_resting_session_renders_finished_unread():
    assert display_state(StatusSeed(STATUS_IDLE), unread=True) == (
        STATUS_FINISHED_UNREAD
    )
    assert display_state(StatusSeed(STATUS_IDLE), unread=False) == STATUS_IDLE


def test_a_refusal_renders_as_nothing_at_all():
    assert display_state(StatusSeed(), unread=True) is None




def test_seeding_twice_leaves_the_same_state():
    store = SessionStatusSeeds()
    seed = StatusSeed(STATUS_IDLE, rung=SEED_RUNG_TRANSCRIPT)
    store.remember("s1", seed, now=NOW)
    store.remember("s1", seed, now=NOW)
    store.remember("s1", seed, now=NOW)
    assert store.get("s1") == seed
    assert store.due("s1", now=NOW) is False


def test_a_never_seeded_session_is_due_and_a_fresh_one_is_not():
    store = SessionStatusSeeds()
    assert store.due("never", now=NOW) is True
    store.remember("s1", StatusSeed(), now=NOW)
    assert store.due("s1", now=NOW) is False
    later = NOW + timedelta(seconds=SEED_REFRESH_INTERVAL_SECONDS + 1)
    assert store.due("s1", now=later) is True


def test_a_clock_that_ran_backwards_still_reads_due():
    store = SessionStatusSeeds()
    store.remember("s1", StatusSeed(), now=NOW)
    assert store.due("s1", now=NOW - timedelta(hours=1)) is True


def test_a_refusal_cached_with_no_epoch_is_due_the_instant_one_is_known():
    store = SessionStatusSeeds()
    store.remember("s1", StatusSeed(), now=NOW, epoch=None)
    assert store.due("s1", now=NOW) is False, (
        "no epoch offered yet - the ordinary clock still applies"
    )
    assert store.due("s1", now=NOW, epoch=42) is True


def test_a_seed_cached_with_a_known_epoch_is_not_forced_due_by_the_same_epoch():
    store = SessionStatusSeeds()
    store.remember("s1", StatusSeed(STATUS_IDLE), now=NOW, epoch=42)
    assert store.due("s1", now=NOW, epoch=42) is False


def test_prune_drops_only_the_sessions_that_are_gone():
    store = SessionStatusSeeds()
    store.remember("live", StatusSeed(STATUS_IDLE), now=NOW)
    store.remember("gone", StatusSeed(STATUS_IDLE), now=NOW)
    assert store.prune(["live"]) == 1
    assert store.get("live") is not None
    assert store.get("gone") is None




@pytest.fixture
def corpus(tmp_path, monkeypatch):
    home = tmp_path / "home"
    projects = home / ".claude" / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return projects


def write_transcript(corpus, working_dir, uuid, records, age_seconds=3600):
    directory = corpus / slugify_project_dir(working_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid}.jsonl"
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    if age_seconds:
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
    return path


def test_a_real_resting_transcript_reads_at_rest(corpus, tmp_path):
    wd = str(tmp_path / "proj")
    write_transcript(corpus, wd, UUID, [user_prompt(), assistant("end_turn"),
                                        turn_duration()])
    assert read_transcript_rest(UUID, wd).verdict == TAIL_AT_REST


def test_a_real_busy_transcript_reads_in_flight(corpus, tmp_path):
    wd = str(tmp_path / "proj")
    write_transcript(corpus, wd, UUID, [turn_duration(), user_prompt()])
    assert read_transcript_rest(UUID, wd).verdict == TAIL_IN_FLIGHT


def test_a_row_with_no_conversation_bound_reads_absent(corpus, tmp_path):
    assert read_transcript_rest(None, str(tmp_path)).verdict == TAIL_ABSENT


def test_a_uuid_with_no_file_reads_absent_not_at_rest(corpus, tmp_path):
    assert read_transcript_rest(UUID, str(tmp_path)).verdict == TAIL_ABSENT


def test_a_half_written_last_line_does_not_break_the_read(corpus, tmp_path):
    wd = str(tmp_path / "proj")
    path = write_transcript(corpus, wd, UUID, [turn_duration()])
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"type": "assist')
    assert read_transcript_rest(UUID, wd).verdict == TAIL_AT_REST




@pytest.mark.asyncio
async def test_boot_seeds_a_resting_session_and_refuses_a_busy_one(
    tmp_path, monkeypatch, corpus
):
    from tests.test_boot_readopt import (
        EPOCH_A,
        EPOCH_B,
        _noop,
        install_backends,
        listing_rows,
        seed_row,
    )
    from src.config import settings
    from src.core.session_manager import SessionManager
    from src.core.tmux_listing import TmuxListing
    from tests.s7_helpers import migrated_connection

    log_dir = tmp_path / "logs"
    state = tmp_path / "state"
    log_dir.mkdir()
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    config_path = tmp_path / "config.json"
    config_path.write_text('{"session": {"tmux_socket_name": "cloude"}}')
    monkeypatch.setattr(settings, "auth_config_file", str(config_path))
    with closing(migrated_connection(state)):
        pass

    resting_dir = str(tmp_path / "resting")
    busy_dir = str(tmp_path / "busy")
    resting_uuid = "11111111-1111-4111-8111-111111111111"
    busy_uuid = "22222222-2222-4222-8222-222222222222"
    write_transcript(corpus, resting_dir, resting_uuid,
                     [user_prompt(), assistant("end_turn"), turn_duration()])
    write_transcript(corpus, busy_dir, busy_uuid,
                     [turn_duration(), user_prompt(), assistant("tool_use")])

    mgr = SessionManager()
    monkeypatch.setattr(mgr, "_sweep_orphan_uploads", _noop)
    seed_row(state, mgr, name="cloude_resting", epoch=EPOCH_A,
             working_dir=resting_dir, agent_type="claude")
    seed_row(state, mgr, name="cloude_busy", epoch=EPOCH_B,
             working_dir=busy_dir, agent_type="claude")
    with closing(connect(db_path_for(state))) as conn:
        conn.execute(
            "UPDATE sessions SET claude_session_uuid = ? WHERE tmux_name = ?",
            (resting_uuid, "cloude_resting"),
        )
        conn.execute(
            "UPDATE sessions SET claude_session_uuid = ? WHERE tmux_name = ?",
            (busy_uuid, "cloude_busy"),
        )
        conn.commit()

    install_backends(
        monkeypatch,
        discover=TmuxListing.answered(["cloude_resting", "cloude_busy"]),
        attachable=listing_rows(("cloude_resting", EPOCH_A),
                                ("cloude_busy", EPOCH_B)),
    )

    await mgr.lifespan_startup()
    await mgr._boot_readopt_task

    store = seeds_for(mgr)
    by_name = {b.tmux_session: sid for sid, b in mgr._registry.backends.items()}
    resting_seed = store.get(by_name["cloude_resting"])
    busy_seed = store.get(by_name["cloude_busy"])

    assert resting_seed is not None and resting_seed.state == STATUS_IDLE
    assert resting_seed.rung == SEED_RUNG_TRANSCRIPT
    assert busy_seed is not None and busy_seed.state is None


@pytest.mark.asyncio
async def test_a_row_state_survives_the_restart_and_beats_the_transcript(
    tmp_path, monkeypatch, corpus
):
    from tests.test_boot_readopt import EPOCH_A, EPOCH_B, seed_row
    from src.config import settings
    from src.core.session_manager import SessionManager
    from tests.s7_helpers import migrated_connection

    log_dir = tmp_path / "logs"
    state = tmp_path / "state"
    log_dir.mkdir()
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    with closing(migrated_connection(state)):
        pass

    mgr = SessionManager()
    seed_row(state, mgr, name="cloude_twin", epoch=EPOCH_A,
             working_dir=str(tmp_path), agent_type="claude")
    seed_row(state, mgr, name="cloude_twin", epoch=EPOCH_B,
             working_dir=str(tmp_path), agent_type="claude")
    with closing(connect(db_path_for(state))) as conn:
        write_state(conn, "cloude_twin", STATUS_IDLE, EPOCH_A,
                    tmux_socket=mgr.tmux_socket_name())
        write_state(conn, "cloude_twin", STATUS_WORKING, EPOCH_B,
                    tmux_socket=mgr.tmux_socket_name())
        conn.commit()

    seed = derive_seed(mgr, "ses_twin", "cloude_twin", epoch=EPOCH_A)
    assert seed.state == STATUS_IDLE
    assert seed.rung == SEED_RUNG_ROW


@pytest.mark.asyncio
async def test_a_session_with_live_hook_signal_is_still_seeded(
    tmp_path, monkeypatch, corpus
):
    from tests.test_boot_readopt import EPOCH_A, seed_row
    from src.config import settings
    from src.core.session_manager import SessionManager
    from src.models import Session
    from tests.s7_helpers import migrated_connection

    log_dir = tmp_path / "logs"
    state = tmp_path / "state"
    log_dir.mkdir()
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    with closing(migrated_connection(state)):
        pass

    wd = str(tmp_path / "proj")
    write_transcript(corpus, wd, UUID, [turn_duration()])

    mgr = SessionManager()
    seed_row(state, mgr, name="cloude_hooked", epoch=EPOCH_A, working_dir=wd,
             agent_type="claude")
    with closing(connect(db_path_for(state))) as conn:
        conn.execute(
            "UPDATE sessions SET claude_session_uuid = ? WHERE tmux_name = ?",
            (UUID, "cloude_hooked"),
        )
        conn.commit()

    session = Session(id="ses_hooked", working_dir=wd)
    session.tmux_session = "cloude_hooked"
    mgr._registry.sessions["ses_hooked"] = session
    mgr._instance_epochs["ses_hooked"] = EPOCH_A

    assert seed_live_sessions(mgr) == (1, 1)
    assert seeds_for(mgr).get("ses_hooked").state == STATUS_IDLE

    assert seed_live_sessions(mgr) == (1, 1)


@pytest.mark.asyncio
async def test_an_unidentifiable_instance_seeds_nothing(tmp_path, monkeypatch):
    from src.config import settings
    from src.core.session_manager import SessionManager
    from tests.s7_helpers import migrated_connection

    state = tmp_path / "state"
    log_dir = tmp_path / "logs"
    state.mkdir()
    log_dir.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    with closing(migrated_connection(state)):
        pass

    mgr = SessionManager()
    seed = derive_seed(mgr, "ses_x", "cloude_x", epoch=None)
    assert seed.state is None
    assert seed.rung == SEED_RUNG_NONE
    assert "could not be identified" in (seed.detail or "")




@pytest.mark.asyncio
async def test_seeded_status_retries_a_refusal_once_the_epoch_is_known(
    tmp_path, monkeypatch
):
    from tests.test_boot_readopt import EPOCH_A, seed_row
    from src.config import settings
    from src.core.session_manager import SessionManager
    from tests.s7_helpers import migrated_connection

    log_dir = tmp_path / "logs"
    state = tmp_path / "state"
    log_dir.mkdir()
    state.mkdir()
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    with closing(migrated_connection(state)):
        pass

    mgr = SessionManager()
    seed_row(state, mgr, name="cloude_PT-IMC", epoch=EPOCH_A,
              working_dir=str(tmp_path), agent_type="claude")
    with closing(connect(db_path_for(state))) as conn:
        write_state(conn, "cloude_PT-IMC", STATUS_IDLE, EPOCH_A,
                    tmux_socket=mgr.tmux_socket_name())
        conn.commit()

    refused = seeded_status(mgr, "ses_pt_imc", "cloude_PT-IMC", now=NOW)
    assert refused is None
    assert seeds_for(mgr).get("ses_pt_imc").rung == SEED_RUNG_NONE

    mgr._instance_epochs["ses_pt_imc"] = EPOCH_A

    healed = seeded_status(mgr, "ses_pt_imc", "cloude_PT-IMC", now=NOW)
    assert healed == STATUS_IDLE


def test_a_broken_datastore_read_logs_at_warning_not_debug():

    class _BrokenConn:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("no such table: sessions")

        def close(self):
            pass

    class _FakeManager:
        def _writable_datastore_connection(self):
            return _BrokenConn()

        def tmux_socket_name(self):
            return "cloudetest"

    with structlog.testing.capture_logs() as logs:
        row = read_instance_row(
            _FakeManager(), "cloude_x", 123, session_id="ses_broken"
        )

    assert row is None
    failures = [
        entry for entry in logs
        if entry.get("event") == "status_seed_row_read_failed"
    ]
    assert len(failures) == 1, f"expected exactly one failure log, got {logs}"
    entry = failures[0]
    assert entry["log_level"] == "warning"
    assert entry["session_id"] == "ses_broken"
    assert entry["error_type"] == "OperationalError"

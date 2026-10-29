
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from src.core.attention.codex_reader import (
    CODEX_RECORD_ABSENT,
    CODEX_RECORD_BUSY,
    CODEX_RECORD_REST,
    CODEX_TURN_COMPLETED,
    CODEX_TURN_FAILED,
    CODEX_TURN_INTERRUPTED,
)
from src.core.attention.codex_stores import (
    pick_primary_conversation,
    read_codex_record,
    read_codex_transcript,
)

CWD = "/Users/x/proj"


def _thread(uuid, *, source="user", name=None, archived=0, cwd=CWD, recency=0):
    return {
        "id": uuid,
        "thread_source": source,
        "name": name,
        "archived": archived,
        "cwd": cwd,
        "recency_at": recency,
    }


def test_pick_leads_with_the_live_lock_holder_even_when_unnamed():
    threads = [
        _thread("u1", name=None),
        _thread("u2", name=None),
        _thread("u3", name="something"),
        _thread("s1", source="subagent"),
    ]
    got = pick_primary_conversation(
        threads,
        pane_current_path=CWD,
        pane_title="anything",
        live_lock_uuids={"u2"},
    )
    assert got == "u2"


def test_pick_uses_name_when_lock_is_ambiguous():
    threads = [_thread("u1", name="mywork"), _thread("u2", name="other")]
    got = pick_primary_conversation(
        threads,
        pane_current_path=CWD,
        pane_title="mywork | proj",
        live_lock_uuids=set(),
    )
    assert got == "u1"


def test_pick_degrades_to_none_when_ambiguous():
    threads = [_thread("u1", name=None), _thread("u2", name=None)]
    got = pick_primary_conversation(
        threads,
        pane_current_path=CWD,
        pane_title="unmatched",
        live_lock_uuids=set(),
    )
    assert got is None


def test_pick_ignores_subagents_and_other_cwds():
    threads = [
        _thread("s1", source="subagent"),
        _thread("u_elsewhere", cwd="/other"),
        _thread("u_here"),
    ]
    got = pick_primary_conversation(
        threads,
        pane_current_path=CWD,
        pane_title="x",
        live_lock_uuids=set(),
    )
    assert got == "u_here"

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
THREAD = "ad166ca4-f8b4-989f-dee8-b5b4f34999e3"


def _make_history_db(path, turns, *, projection_offset=1000):
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE thread_turns (thread_id TEXT NOT NULL, turn_id TEXT "
        "NOT NULL, rollout_ordinal INTEGER NOT NULL, status TEXT NOT NULL, "
        "error_json TEXT, started_at INTEGER, completed_at INTEGER, "
        "duration_ms INTEGER, first_user_item_id TEXT, final_agent_item_id "
        "TEXT, PRIMARY KEY (thread_id, turn_id))"
    )
    con.execute(
        "CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY "
        "KEY, next_rollout_byte_offset INTEGER NOT NULL, next_rollout_ordinal "
        "INTEGER NOT NULL)"
    )
    for i, (status, err) in enumerate(turns):
        con.execute(
            "INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, "
            "status, error_json) VALUES (?, ?, ?, ?, ?)",
            (THREAD, "turn_%d" % i, i, status, err),
        )
    con.execute(
        "INSERT INTO thread_history_projection_state VALUES (?, ?, ?)",
        (THREAD, projection_offset, len(turns)),
    )
    con.commit()
    con.close()




def test_completed_last_turn_is_rest_completed(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    _make_history_db(db, [("completed", None), ("completed", None)])
    facts = read_codex_record(db, THREAD, lock_live=False)
    assert facts.verdict == CODEX_RECORD_REST
    assert facts.rest_kind == CODEX_TURN_COMPLETED


def test_inprogress_with_live_lock_is_busy(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    _make_history_db(db, [("completed", None), ("inProgress", None)])
    facts = read_codex_record(db, THREAD, lock_live=True)
    assert facts.verdict == CODEX_RECORD_BUSY


def test_inprogress_without_live_lock_is_absent(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    _make_history_db(db, [("inProgress", None)])
    facts = read_codex_record(db, THREAD, lock_live=False)
    assert facts.verdict == CODEX_RECORD_ABSENT


def test_interrupted_and_failed_carry_their_kind(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    _make_history_db(db, [("interrupted", None)])
    assert read_codex_record(db, THREAD, lock_live=False).rest_kind == (
        CODEX_TURN_INTERRUPTED
    )
    db2 = tmp_path / "thread_history_1b.sqlite"
    _make_history_db(db2, [("failed", '{"message":"boom"}')])
    assert read_codex_record(db2, THREAD, lock_live=False).rest_kind == (
        CODEX_TURN_FAILED
    )


def test_stale_projection_watermark_demotes_a_busy_to_absent(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    _make_history_db(db, [("inProgress", None)], projection_offset=1000)
    facts = read_codex_record(db, THREAD, lock_live=True, rollout_size=9_000_000)
    assert facts.verdict == CODEX_RECORD_ABSENT


def test_no_row_for_the_thread_is_absent(tmp_path):
    db = tmp_path / "thread_history_1.sqlite"
    _make_history_db(db, [("completed", None)])
    facts = read_codex_record(db, "unknown-thread", lock_live=True)
    assert facts.verdict == CODEX_RECORD_ABSENT


def test_a_missing_db_is_absent_not_a_raise(tmp_path):
    facts = read_codex_record(tmp_path / "nope.sqlite", THREAD, lock_live=True)
    assert facts.verdict == CODEX_RECORD_ABSENT




def _line(ordinal, rtype, payload, ts=None):
    return json.dumps(
        {
            "timestamp": (ts or NOW).isoformat(),
            "ordinal": ordinal,
            "type": rtype,
            "payload": payload,
        }
    )


def _fc(name, call_id, ordinal, ts=None):
    return _line(
        ordinal,
        "response_item",
        {"type": "function_call", "name": name, "call_id": call_id,
         "arguments": "{}"},
        ts=ts,
    )


def _fco(call_id, ordinal, ts=None):
    return _line(
        ordinal,
        "response_item",
        {"type": "function_call_output", "call_id": call_id},
        ts=ts,
    )


def _event(name, ordinal, ts=None):
    return _line(ordinal, "event_msg", {"type": name, "turn_id": "t1"}, ts=ts)


def _write(tmp_path, lines):
    p = tmp_path / ("rollout-2026-09-12T10-48-49-%s.jsonl" % THREAD)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_open_request_user_input_is_a_question(tmp_path):
    p = _write(
        tmp_path,
        [
            _event("task_started", 0),
            _fc("request_user_input", "call_q", 1),
        ],
    )
    facts = read_codex_transcript(p, now=NOW)
    assert facts.question_open is True
    assert facts.readable is True


def test_answered_request_user_input_is_not_a_question(tmp_path):
    p = _write(
        tmp_path,
        [
            _fc("request_user_input", "call_q", 0),
            _fco("call_q", 1),
        ],
    )
    assert read_codex_transcript(p, now=NOW).question_open is False


def test_outstanding_wait_agent_is_subagents_waiting(tmp_path):
    p = _write(
        tmp_path,
        [
            _event("task_started", 0),
            _fc("wait_agent", "call_w", 1),
        ],
    )
    assert read_codex_transcript(p, now=NOW).subagents_waiting is True


def test_wait_agent_is_voided_by_a_task_complete(tmp_path):
    p = _write(
        tmp_path,
        [
            _fc("wait_agent", "call_w", 0),
            _event("task_complete", 1),
        ],
    )
    assert read_codex_transcript(p, now=NOW).subagents_waiting is False


def test_wait_agent_is_voided_by_a_turn_abort(tmp_path):
    p = _write(
        tmp_path,
        [
            _fc("wait_agent", "call_w", 0),
            _event("turn_aborted", 1),
        ],
    )
    assert read_codex_transcript(p, now=NOW).subagents_waiting is False


def test_wait_agent_matched_by_output_is_not_waiting(tmp_path):
    p = _write(
        tmp_path,
        [
            _fc("wait_agent", "call_w", 0),
            _fco("call_w", 1),
        ],
    )
    assert read_codex_transcript(p, now=NOW).subagents_waiting is False


def test_an_old_outstanding_wait_is_age_bounded_off(tmp_path):
    old = NOW - timedelta(hours=6)
    p = _write(
        tmp_path,
        [
            _event("task_started", 0, ts=old),
            _fc("wait_agent", "call_w", 1, ts=old),
        ],
    )
    assert read_codex_transcript(p, now=NOW).subagents_waiting is False


def test_a_trailing_token_count_is_not_still_running(tmp_path):
    p = _write(
        tmp_path,
        [
            _fc("wait_agent", "call_w", 0),
            _event("task_complete", 1),
            _line(2, "event_msg", {"type": "token_count", "turn_id": "t1"}),
        ],
    )
    assert read_codex_transcript(p, now=NOW).subagents_waiting is False


def test_an_over_long_line_is_guarded_not_parsed(tmp_path):
    giant = json.dumps(
        {"timestamp": NOW.isoformat(), "ordinal": 9, "type": "compacted",
         "payload": {"blob": "x" * (128 * 1024)}}
    )
    p = _write(
        tmp_path,
        [
            _fc("request_user_input", "call_q", 0),
            giant,
        ],
    )
    facts = read_codex_transcript(p, now=NOW)
    assert facts.readable is True
    assert facts.question_open is True


def test_a_missing_rollout_is_unreadable_not_a_raise(tmp_path):
    facts = read_codex_transcript(tmp_path / "nope.jsonl", now=NOW)
    assert facts.readable is False

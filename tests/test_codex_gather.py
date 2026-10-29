
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from src.core.attention.codex_gather import gather_codex_evidence, rollout_path_for
from src.core.attention.codex_reader import (
    CODEX_RECORD_REST,
    CODEX_TURN_COMPLETED,
    CodexEvidence,
)

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)
THREAD = "ad166ca4-f8b4-989f-dee8-b5b4f34999e3"


def _make_codex_home(tmp_path):
    home = tmp_path / ".codex"
    (home / "sessions" / "2026" / "09" / "12").mkdir(parents=True)
    (home / "thread-writer-locks").mkdir(parents=True)
    con = sqlite3.connect(str(home / "thread_history_1.sqlite"))
    con.execute(
        "CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, "
        "rollout_ordinal INTEGER, status TEXT, error_json TEXT)"
    )
    con.execute(
        "INSERT INTO thread_turns VALUES (?, 't0', 0, 'completed', NULL)",
        (THREAD,),
    )
    con.execute(
        "CREATE TABLE thread_history_projection_state (thread_id TEXT, "
        "next_rollout_byte_offset INTEGER, next_rollout_ordinal INTEGER)"
    )
    con.commit()
    con.close()
    rollout = (
        home / "sessions" / "2026" / "09" / "12"
        / ("rollout-2026-09-12T10-48-49-%s.jsonl" % THREAD)
    )
    rollout.write_text(
        '{"timestamp":"%s","ordinal":0,"type":"event_msg",'
        '"payload":{"type":"task_complete","turn_id":"t0"}}\n' % NOW.isoformat(),
        encoding="utf-8",
    )
    con = sqlite3.connect(str(home / "state_5.sqlite"))
    con.execute(
        "CREATE TABLE threads (id TEXT, rollout_path TEXT, cwd TEXT, "
        "thread_source TEXT, name TEXT, recency_at INTEGER, archived INTEGER)"
    )
    con.execute(
        "INSERT INTO threads VALUES (?, ?, '/p', 'user', NULL, 0, 0)",
        (THREAD, str(rollout)),
    )
    con.commit()
    con.close()
    return home, rollout


def test_rollout_path_is_resolved_from_the_state_db(tmp_path):
    home, rollout = _make_codex_home(tmp_path)
    assert rollout_path_for(str(home), THREAD) == str(rollout)


def test_gather_builds_a_bundle_that_resolves_to_done(tmp_path):
    home, _ = _make_codex_home(tmp_path)
    ce = gather_codex_evidence(THREAD, codex_home=str(home), now=NOW)
    assert isinstance(ce, CodexEvidence)
    assert ce.record.verdict == CODEX_RECORD_REST
    assert ce.record.rest_kind == CODEX_TURN_COMPLETED
    assert ce.pane is None


def test_gather_without_a_uuid_is_none():
    assert gather_codex_evidence(None, codex_home="/nope", now=NOW) is None


def test_gather_on_a_missing_home_is_fail_soft(tmp_path):
    ce = gather_codex_evidence(THREAD, codex_home=str(tmp_path / "gone"), now=NOW)
    assert ce is None or isinstance(ce, CodexEvidence)


from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.core.session_token_usage.reader import SessionSubject
from src.core.subagents import files, shape_alert
from src.core.subagents.files import LineFacts
from src.core.subagents.parent_index import (
    CompletionIndex,
    RecordedEnd,
    _notifications,
    read_completion_index,
)
from src.core.subagents.reader import SILENT_AFTER, classify, read_subagents
from src.core.subagents.session import read_session_subagents
from src.core.session_token_usage.cache import IncrementalCache
from tests.helpers.subagent_fixture import A, B, C, CONV, D, E, F, G, H, I, PROJECT_DIR, build_corpus

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_caches():
    files.reset_caches_for_tests()
    shape_alert.reset_for_tests()
    yield
    files.reset_caches_for_tests()
    shape_alert.reset_for_tests()


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    target = tmp_path / "projects"
    build_corpus(target)
    return target


def _transcript(corpus: Path) -> Path:
    return corpus / PROJECT_DIR / f"{CONV}.jsonl"


def _by_id(result):
    return {row.id: row for row in result.subagents}


def test_every_fixture_case_gets_the_status_its_evidence_proves(corpus):
    result = read_subagents(_transcript(corpus), conversation_uuid=CONV, now=NOW)
    rows = _by_id(result)
    assert result.state == "ok"
    expected = {
        A: ("done", "end_recorded"),
        B: ("running", "no_end_recorded"),
        C: ("done", "end_recorded"),
        D: ("done", "end_recorded"),
        E: ("unknown", "silent"),
        F: ("running", "resumed_after_end"),
        G: ("done", "end_recorded"),
        H: ("unknown", "shape_unrecognized"),
        I: ("running", "no_end_recorded"),
    }
    assert {k: (rows[k].status, rows[k].status_reason) for k in expected} == expected


def test_counts_never_fold_unknown_into_running_or_done(corpus):
    counts = read_subagents(_transcript(corpus), conversation_uuid=CONV, now=NOW).counts
    assert (counts.total, counts.listed) == (9, 9)
    assert (counts.running, counts.done, counts.unknown) == (3, 4, 2)
    assert counts.running + counts.done + counts.unknown == counts.listed
    assert counts.shape_unrecognized == 2
    assert counts.internal == 1


def test_meta_fields_reach_the_wire(corpus):
    rows = _by_id(read_subagents(_transcript(corpus), conversation_uuid=CONV, now=NOW))
    b = rows[B]
    assert (b.agent_type, b.description, b.model) == ("worker", "fixture background", "claude-fixture")
    assert b.background is True and b.spawn_depth == 1
    assert rows[A].background is None
    assert rows[D].spawn_depth == 2
    assert b.started_at == "2026-09-26T10:10:00Z"
    assert b.last_activity_at == "2026-09-26T11:58:00Z"
    assert rows[C].end_status == "completed"
    assert rows[B].end_status is None


def test_a_harness_injection_is_not_activity(corpus):
    row = _by_id(read_subagents(_transcript(corpus), conversation_uuid=CONV, now=NOW))[C]
    assert row.last_activity_at == "2026-09-26T10:29:00Z"


def test_a_changed_meta_shape_is_named_and_the_status_still_comes_from_evidence(corpus):
    row = _by_id(read_subagents(_transcript(corpus), conversation_uuid=CONV, now=NOW))[G]
    assert row.meta_shape == "shape_unrecognized"
    assert row.agent_type is None
    assert row.status == "done"


def test_a_torn_last_line_is_not_a_shape_change(corpus):
    row = _by_id(read_subagents(_transcript(corpus), conversation_uuid=CONV, now=NOW))[I]
    assert row.transcript_shape == "ok"
    assert row.last_activity_at == "2026-09-26T11:52:00Z"


def test_the_list_is_capped_newest_first_and_the_total_still_counts_all(corpus):
    result = read_subagents(_transcript(corpus), conversation_uuid=CONV, now=NOW, max_listed=2)
    assert result.counts.total == 9 and result.counts.listed == 2
    assert "7 oldest" in result.detail


def test_no_subagents_directory_is_a_measured_zero(tmp_path):
    transcript = tmp_path / "p" / f"{CONV}.jsonl"
    transcript.parent.mkdir()
    transcript.write_text("")
    result = read_subagents(transcript, conversation_uuid=CONV, now=NOW)
    assert result.state == "ok"
    assert result.counts.total == 0 and result.counts.running == 0


def test_an_unreadable_parent_makes_every_status_unknown(corpus, monkeypatch):
    import src.core.subagents.reader as reader_mod

    monkeypatch.setattr(reader_mod, "read_completion_index", lambda *a, **k: None)
    result = read_subagents(_transcript(corpus), conversation_uuid=CONV, now=NOW)
    assert {row.status for row in result.subagents} == {"unknown"}
    assert result.counts.done == 0 and result.counts.running == 0


def test_codex_contributes_no_count_not_a_zero():
    result = read_session_subagents(SessionSubject("codex", "t-1", None), now=NOW)
    assert result.state == "not_applicable"
    assert result.counts is None


def test_a_session_with_no_conversation_is_a_measured_absence():
    result = read_session_subagents(SessionSubject("claude", None, None), now=NOW)
    assert result.state == "absent" and result.counts.total == 0


def test_the_session_dispatch_locates_the_transcript(corpus):
    result = read_session_subagents(
        SessionSubject("claude", CONV, None), projects_dir=corpus, now=NOW)
    assert result.state == "ok" and result.counts.total == 9




def _line(last_at):
    return LineFacts("ok", started_at=last_at, last_at=last_at)


def test_an_agent_older_than_the_current_process_is_not_running():
    last = NOW - timedelta(minutes=5)
    assert classify(line=_line(last), end=None, index_available=True,
                    process_started_at=NOW - timedelta(minutes=1), now=NOW) == (
        "unknown", "process_restarted")
    assert classify(line=_line(last), end=None, index_available=True,
                    process_started_at=NOW - timedelta(minutes=10), now=NOW) == (
        "running", "no_end_recorded")


def test_silence_past_the_window_is_unknown_not_running():
    last = NOW - SILENT_AFTER - timedelta(seconds=1)
    assert classify(line=_line(last), end=None, index_available=True,
                    process_started_at=None, now=NOW)[0] == "unknown"


def test_an_end_recorded_before_later_activity_does_not_prove_done():
    last = NOW - timedelta(minutes=1)
    end = RecordedEnd(last - timedelta(minutes=10), "completed")
    assert classify(line=_line(last), end=end, index_available=True,
                    process_started_at=None, now=NOW) == ("running", "resumed_after_end")


def test_one_notification_block_can_end_several_agents():
    text = ("<task-notification>\n<task-id>a1</task-id>\n<task-id>a2</task-id>\n"
            "<status>stopped</status>\n</task-notification>")
    assert list(_notifications(text)) == [("a1", "stopped"), ("a2", "stopped")]


def test_the_parent_index_resumes_from_where_it_stopped(corpus):
    cache = IncrementalCache()
    path = _transcript(corpus)
    first = read_completion_index(path, cache=cache)
    assert isinstance(first, CompletionIndex) and C in first.by_agent_id
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"type":"queue-operation","operation":"enqueue",'
                     '"timestamp":"2026-09-26T11:59:00.000Z","content":'
                     '"<task-notification><task-id>a5000000000000005</task-id>'
                     '<status>killed</status></task-notification>"}\n')
    second = read_completion_index(path, cache=cache)
    assert second.by_agent_id[E].status == "killed"
    assert E not in first.by_agent_id


def test_a_cold_parent_over_the_cap_is_refused(corpus):
    assert read_completion_index(_transcript(corpus), cache=IncrementalCache(),
                                 max_cold_bytes=10) is None

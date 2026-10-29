
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import json

import pytest

from src.core import claude_rename_retry_store as store
from src.core.claude_rename_retry import (
    MAX_PUSH_ATTEMPTS,
    MIN_ATTEMPT_INTERVAL_SECONDS,
    RETRY_AGREED,
    RETRY_EXHAUSTED,
    RETRY_PUSH,
    RETRY_SUPERSEDED,
    RETRY_UNORDERED,
    RETRY_UNREADABLE,
    RETRY_WAITING,
    RenameMark,
    budget_for,
    decide_retry,
    record_agreement,
    record_attempt,
    witness_agreement,
)
from src.core.claude_title_sync import (
    TITLE_APPLIED,
    TITLE_BASELINE_RECORDED,
    TITLE_NOT_MEASURED,
    TITLE_UNCHANGED,
)

OLD = "Agent - Larkspur (alpha)"
NEW = "Agent - Larkspur (Remotedesk)"


def _agreed_on(name: str) -> RenameMark:
    seen = witness_agreement(title=name, claude_title=name)
    assert seen == name
    return record_agreement(None, seen)




def test_a_divergence_with_no_witnessed_agreement_is_refused():
    decision = decide_retry(
        sync_action=TITLE_UNCHANGED,
        title=NEW,
        claude_title=OLD,
        mark=None,
        now=0.0,
    )
    assert decision.verdict == RETRY_UNORDERED
    assert decision.acts is False
    assert decision.label is None


def test_a_mark_that_has_been_overtaken_is_refused():
    decision = decide_retry(
        sync_action=TITLE_UNCHANGED,
        title=NEW,
        claude_title="a third name",
        mark=_agreed_on(OLD),
        now=0.0,
    )
    assert decision.verdict == RETRY_UNORDERED
    assert decision.acts is False


def test_a_rename_typed_in_the_tui_supersedes_the_pending_push():
    decision = decide_retry(
        sync_action=TITLE_APPLIED,
        title=NEW,
        claude_title=OLD,
        mark=_agreed_on(OLD),
        now=0.0,
    )
    assert decision.verdict == RETRY_SUPERSEDED
    assert decision.acts is False


def test_a_first_sight_baseline_never_authorises_a_push():
    decision = decide_retry(
        sync_action=TITLE_BASELINE_RECORDED,
        title=NEW,
        claude_title=OLD,
        mark=_agreed_on(OLD),
        now=0.0,
    )
    assert decision.verdict == RETRY_SUPERSEDED
    assert decision.acts is False


def test_an_unreadable_transcript_decides_nothing_and_spends_nothing():
    decision = decide_retry(
        sync_action=TITLE_NOT_MEASURED,
        title=NEW,
        claude_title=OLD,
        mark=_agreed_on(OLD),
        now=0.0,
    )
    assert decision.verdict == RETRY_UNREADABLE
    assert decision.acts is False
    assert decision.attempts_spent == 0


def test_agreement_between_the_two_columns_is_the_quiet_steady_state():
    decision = decide_retry(
        sync_action=TITLE_UNCHANGED,
        title=OLD,
        claude_title=OLD,
        mark=_agreed_on(OLD),
        now=0.0,
    )
    assert decision.verdict == RETRY_AGREED
    assert decision.acts is False


def test_a_null_claude_title_is_not_an_agreement_and_not_a_divergence():
    assert witness_agreement(title=NEW, claude_title=None) is None
    assert witness_agreement(title=None, claude_title=None) is None
    assert witness_agreement(title=NEW, claude_title="   ") is None
    decision = decide_retry(
        sync_action=TITLE_UNCHANGED,
        title=NEW,
        claude_title=None,
        mark=None,
        now=0.0,
    )
    assert decision.verdict == RETRY_AGREED




def test_a_browser_rename_after_a_witnessed_agreement_is_pushed():
    mark = _agreed_on(OLD)
    decision = decide_retry(
        sync_action=TITLE_UNCHANGED,
        title=NEW,
        claude_title=OLD,
        mark=mark,
        now=1000.0,
    )
    assert decision.verdict == RETRY_PUSH
    assert decision.acts is True
    assert decision.label == NEW
    assert decision.attempts_spent == 0




def test_a_permanently_unreachable_session_stops_in_a_named_state():
    mark = _agreed_on(OLD)
    now = 1000.0
    for expected in range(MAX_PUSH_ATTEMPTS):
        decision = decide_retry(
            sync_action=TITLE_UNCHANGED,
            title=NEW,
            claude_title=OLD,
            mark=mark,
            now=now,
        )
        assert decision.verdict == RETRY_PUSH
        assert decision.attempts_spent == expected
        mark = record_attempt(mark, label=NEW, now=now)
        now += MIN_ATTEMPT_INTERVAL_SECONDS * 2

    for _ in range(3):
        decision = decide_retry(
            sync_action=TITLE_UNCHANGED,
            title=NEW,
            claude_title=OLD,
            mark=mark,
            now=now,
        )
        assert decision.verdict == RETRY_EXHAUSTED
        assert decision.acts is False
        assert decision.attempts_spent == MAX_PUSH_ATTEMPTS
        now += MIN_ATTEMPT_INTERVAL_SECONDS * 2


def test_the_interval_floor_holds_without_spending_an_attempt():
    mark = record_attempt(_agreed_on(OLD), label=NEW, now=1000.0)
    decision = decide_retry(
        sync_action=TITLE_UNCHANGED,
        title=NEW,
        claude_title=OLD,
        mark=mark,
        now=1000.0 + MIN_ATTEMPT_INTERVAL_SECONDS / 2,
    )
    assert decision.verdict == RETRY_WAITING
    assert decision.acts is False
    assert decision.attempts_spent == 1

    later = decide_retry(
        sync_action=TITLE_UNCHANGED,
        title=NEW,
        claude_title=OLD,
        mark=mark,
        now=1000.0 + MIN_ATTEMPT_INTERVAL_SECONDS + 1,
    )
    assert later.verdict == RETRY_PUSH


def test_renaming_again_starts_a_fresh_budget():
    mark = _agreed_on(OLD)
    for _ in range(MAX_PUSH_ATTEMPTS):
        mark = record_attempt(mark, label=NEW, now=0.0)
    assert budget_for(mark, NEW) == MAX_PUSH_ATTEMPTS
    assert budget_for(mark, "a later name") == 0

    decision = decide_retry(
        sync_action=TITLE_UNCHANGED,
        title="a later name",
        claude_title=OLD,
        mark=mark,
        now=10_000.0,
    )
    assert decision.verdict == RETRY_PUSH
    assert decision.label == "a later name"


def test_an_attempt_carries_the_ordering_frame_through_untouched():
    mark = record_attempt(_agreed_on(OLD), label=NEW, now=5.0)
    assert mark.agreed_title == OLD
    assert mark.attempts == 1
    assert mark.last_attempt_at == 5.0


def test_an_agreement_clears_a_pending_budget():
    mark = record_attempt(_agreed_on(OLD), label=NEW, now=5.0)
    settled = record_agreement(mark, NEW)
    assert settled.agreed_title == NEW
    assert settled.attempts == 0
    assert settled.attempted_label is None
    assert settled.last_attempt_at is None




@pytest.fixture
def ledger(tmp_path):
    store.reset_cache()
    yield tmp_path
    store.reset_cache()


def test_a_mark_survives_the_process_that_wrote_it(ledger):
    store.save_mark(ledger, "u1:7", _agreed_on(OLD))
    store.reset_cache()

    recovered = store.mark_for(ledger, "u1:7")
    assert recovered is not None
    assert recovered.agreed_title == OLD


def test_a_spent_budget_survives_a_restart(ledger):
    mark = _agreed_on(OLD)
    for _ in range(MAX_PUSH_ATTEMPTS):
        mark = record_attempt(mark, label=NEW, now=1.0)
        store.save_mark(ledger, "u1:7", mark)
    store.reset_cache()

    assert budget_for(store.mark_for(ledger, "u1:7"), NEW) == MAX_PUSH_ATTEMPTS


def test_a_corrupt_ledger_fails_closed(ledger):
    path = store.ledger_path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    store.reset_cache()

    assert store.load_marks(ledger) == {}
    assert store.mark_for(ledger, "u1:7") is None
    assert (
        decide_retry(
            sync_action=TITLE_UNCHANGED,
            title=NEW,
            claude_title=OLD,
            mark=store.mark_for(ledger, "u1:7"),
            now=0.0,
        ).verdict
        == RETRY_UNORDERED
    )


def test_a_ledger_from_an_unrecognised_version_fails_closed(ledger):
    path = store.ledger_path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 99, "marks": {"u1:7": {"agreed_title": OLD}}}),
        encoding="utf-8",
    )
    store.reset_cache()
    assert store.load_marks(ledger) == {}


def test_a_state_directory_that_cannot_be_named_reads_as_empty():
    store.reset_cache()
    assert store.load_marks(None) == {}
    assert store.mark_for(None, "u1:7") is None
    assert store.save_mark(None, "u1:7", _agreed_on(OLD)) is False
    store.reset_cache()


def test_an_unchanged_mark_does_not_rewrite_the_file(ledger):
    mark = _agreed_on(OLD)
    assert store.save_mark(ledger, "u1:7", mark) is True
    before = store.ledger_path(ledger).stat().st_mtime_ns
    assert store.save_mark(ledger, "u1:7", mark) is False
    assert store.ledger_path(ledger).stat().st_mtime_ns == before


def test_the_ledger_cannot_grow_without_bound(ledger):
    pending = record_attempt(_agreed_on(OLD), label=NEW, now=500.0)
    store.save_mark(ledger, "pending:1", pending)
    for index in range(store.MAX_ENTRIES + 20):
        store.save_mark(ledger, f"frame:{index}", _agreed_on(OLD))

    marks = store.load_marks(ledger)
    assert len(marks) <= store.MAX_ENTRIES
    assert marks.get("pending:1") == pending

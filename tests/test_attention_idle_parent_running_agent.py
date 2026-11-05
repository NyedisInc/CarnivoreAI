
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from src.core.attention.display import to_display
from src.core.attention.evidence import (
    EvidenceIdentity,
    FAMILY_CLAUDE,
    REASON_QUEUED_REINVOKE,
    REASON_RESTING_PROMPT,
    REASON_SUBAGENTS,
    STATE_BUSY,
    STATE_UNKNOWN,
    Evidence,
)
from src.core.attention.registry_record import REG_STALE, parse_registry_record
from src.core.attention.resolve_verdicts import QUEUED_REINVOKE_FRESH_SECONDS
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import FACTS_FOUND, TranscriptFacts
from src.core.session_status import LIVENESS_LIVE, STATUS_WORKING_SUBAGENT
from src.core.subagents.files import LineFacts
from src.core.subagents.reader import classify
from src.core.subagents.tally import STATE_OK, STATE_UNCHECKED, SubagentTally

NOW = datetime(2026, 11, 3, 15, 30, tzinfo=timezone.utc)
STARTED = NOW - timedelta(hours=1)
IDENTITY = EvidenceIdentity("sock", "carnivore_example", 1, 4242, "u")


def _registry(status: str, *, started_at_ms=...):
    stamped = int((NOW - timedelta(minutes=5)).timestamp() * 1000)
    return parse_registry_record(
        {
            "pid": 4242, "sessionId": "u", "cwd": "/example", "version": "2.1.317",
            "startedAt": int(STARTED.timestamp() * 1000) if started_at_ms is ... else started_at_ms,
            "procStart": "Tue Nov  3 14:30:00 2026", "kind": "interactive",
            "entrypoint": "cli", "tmux": "carnivore_example:@1.%1",
            "updatedAt": stamped, "status": status, "statusUpdatedAt": stamped,
        },
        path_pid=4242,
    )


def _facts() -> TranscriptFacts:
    end = NOW - timedelta(minutes=5)
    return TranscriptFacts(
        verdict=FACTS_FOUND, pending_background_agents=1, pending_field_present=True,
        pending_workflows=None, open_async_agents=1, turn_end_at=end,
        newest_assistant_at=end - timedelta(seconds=1), newest_append_at=end,
        detail="the turn ended with a background agent pending",
    )


def _tally(last_write_ago: Optional[timedelta], *, started: datetime = STARTED) -> SubagentTally:
    last = NOW - last_write_ago
    status, _ = classify(
        line=LineFacts(state="ok", last_at=last, mtime=last), end=None,
        index_available=True, process_started_at=started, now=NOW,
    )
    running = int(status == "running")
    return SubagentTally(STATE_OK, running=running, total=1, unknown=1 - running)


def _verdict(registry, tally: Optional[SubagentTally]):
    return resolve_attention(Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE, registry=registry,
        transcript=_facts(), pane=None, now=NOW, resting_prompt_held=True, subagents=tally, identity=IDENTITY,
    ))


@pytest.mark.parametrize("status", ["idle", "busy"])
def test_an_idle_parent_with_a_running_agent_is_working_with_a_subagent(status):
    verdict = _verdict(_registry(status), _tally(timedelta(seconds=20)))
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_SUBAGENTS), verdict.detail
    assert verdict.pane_may_veto is False
    assert to_display(verdict, unread=False, tmux_status=None) == STATUS_WORKING_SUBAGENT


def test_a_resume_pause_with_no_live_agent_stays_grey():
    tally = _tally(timedelta(hours=2))
    assert tally.running == 0
    verdict = _verdict(_registry("idle"), tally)
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)


def test_a_stale_claim_silent_for_half_an_hour_stays_grey():
    tally = _tally(timedelta(minutes=45), started=NOW - timedelta(hours=3))
    assert tally.running == 0
    verdict = _verdict(_registry("idle"), tally)
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)


@pytest.mark.parametrize(
    "registry, tally",
    [
        pytest.param(_registry("idle"), None, id="no_tally_measured"),
        pytest.param(_registry("idle"), SubagentTally(STATE_UNCHECKED), id="tally_unchecked"),
        pytest.param(
            dataclasses.replace(_registry("idle"), verdict=REG_STALE),
            SubagentTally(STATE_OK, running=1, total=1, unknown=0),
            id="refused_record_never_applied_the_restart_guard",
        ),
    ],
)
def test_without_a_measured_running_agent_and_a_known_record_the_veto_holds(registry, tally):
    verdict = _verdict(registry, tally)
    assert (verdict.state, verdict.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)


def _queued_facts(enqueued_ago: timedelta) -> TranscriptFacts:
    end = NOW - timedelta(minutes=5)
    return TranscriptFacts(
        verdict=FACTS_FOUND, pending_background_agents=0, pending_field_present=True,
        pending_workflows=None, open_async_agents=0, queued_reinvoke=True,
        queued_reinvoke_at=NOW - enqueued_ago, turn_end_at=end,
        newest_assistant_at=end - timedelta(seconds=1), newest_append_at=end,
        detail="a completion is queued",
    )


def _queued_verdict(registry, enqueued_ago: timedelta):
    return resolve_attention(Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE, registry=registry,
        transcript=_queued_facts(enqueued_ago), pane=None, now=NOW, resting_prompt_held=True, identity=IDENTITY,
        subagents=SubagentTally(STATE_OK, running=0, total=1, unknown=0),
    ))


def test_a_fresh_queued_completion_is_working_with_a_subagent_while_claude_is_about_to_reinvoke():
    verdict = _queued_verdict(_registry("idle"), timedelta(seconds=9))
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_QUEUED_REINVOKE), verdict.detail
    assert to_display(verdict, unread=False, tmux_status=None) == STATUS_WORKING_SUBAGENT


def test_a_stale_queue_or_an_unknown_record_still_goes_grey():
    stale = _queued_verdict(_registry("idle"), timedelta(seconds=QUEUED_REINVOKE_FRESH_SECONDS + 30))
    assert (stale.state, stale.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)
    refused = _queued_verdict(dataclasses.replace(_registry("idle"), verdict=REG_STALE), timedelta(seconds=9))
    assert (refused.state, refused.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)
    unstamped = resolve_attention(Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE, registry=_registry("idle"),
        transcript=dataclasses.replace(_queued_facts(timedelta(seconds=9)), queued_reinvoke_at=None),
        pane=None, now=NOW, resting_prompt_held=True, identity=IDENTITY,
    ))
    assert (unstamped.state, unstamped.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)


def test_a_record_that_cannot_prove_this_processs_start_never_confirms_a_running_agent():
    running = SubagentTally(STATE_OK, running=1, total=1, unknown=0)
    no_start = resolve_attention(Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE, registry=_registry("idle", started_at_ms=None),
        transcript=_facts(), pane=None, now=NOW, resting_prompt_held=True, subagents=running, identity=IDENTITY))
    assert (no_start.state, no_start.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)
    other = resolve_attention(Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE, registry=_registry("idle"),
        transcript=_facts(), pane=None, now=NOW, resting_prompt_held=True, subagents=running,
        identity=EvidenceIdentity("sock", "carnivore_example", 1, 4242, "another-conversation")))
    assert (other.state, other.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)


def test_a_queued_notice_written_before_this_process_started_is_not_a_reinvoke_in_flight():
    young_process = _registry("idle", started_at_ms=int((NOW - timedelta(seconds=30)).timestamp() * 1000))
    verdict = _queued_verdict(young_process, timedelta(seconds=60))
    assert verdict.state != STATE_BUSY, verdict.detail
    no_start = _queued_verdict(_registry("idle", started_at_ms=None), timedelta(seconds=9))
    assert (no_start.state, no_start.reason) == (STATE_UNKNOWN, REASON_RESTING_PROMPT)

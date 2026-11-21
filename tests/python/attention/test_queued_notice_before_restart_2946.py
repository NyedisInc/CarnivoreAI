
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.attention.evidence import (
    FAMILY_CLAUDE,
    REASON_QUEUED_REINVOKE,
    REASON_TURN_ENDED,
    STATE_BUSY,
    STATE_DONE_IDLE,
    Evidence,
    EvidenceIdentity,
)
from src.core.attention.registry_record import parse_registry_record
from src.core.attention.resolve import resolve_attention
from src.core.attention.transcript_facts import classify_transcript_records
from src.core.session_status import LIVENESS_LIVE

TURN_END = datetime(2026, 11, 10, 22, 45, 43, 604000, tzinfo=timezone.utc)
QUEUED = datetime(2026, 11, 10, 22, 57, 59, 663000, tzinfo=timezone.utc)
STARTED = datetime(2026, 11, 10, 23, 24, 50, 139000, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 11, 13, 40, tzinfo=timezone.utc)
IDENTITY = EvidenceIdentity("sock", "carnivore_example", 1, 4242, "conv-1")

NOTICE = (
    "<task-notification>\n<task-id>bexample1</task-id>\n"
    "<tool-use-id>toolu_example1</tool-use-id>\n"
    "<output-file>/tmp/example/tasks/bexample1.output</output-file>\n"
    "<status>completed</status>\n<summary>Background command finished</summary>\n"
    "</task-notification>"
)


def _iso(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (at.microsecond // 1000)


def _records(queued_at: datetime) -> list:
    return [
        {"type": "assistant", "isSidechain": False, "timestamp": _iso(TURN_END - timedelta(milliseconds=28)),
         "message": {"role": "assistant", "content": [{"type": "text", "text": "the test run is going now"}]}},
        {"type": "system", "subtype": "turn_duration", "durationMs": 1726495, "messageCount": 242,
         "isMeta": False, "timestamp": _iso(TURN_END), "version": "2.1.321"},
        {"type": "queue-operation", "operation": "enqueue", "timestamp": _iso(queued_at), "content": NOTICE},
        {"type": "queue-operation", "operation": "remove", "reason": "delivered_to_agent",
         "timestamp": _iso(queued_at + timedelta(milliseconds=133)), "content": NOTICE},
        {"type": "system", "subtype": "informational", "level": "warning", "isMeta": False,
         "timestamp": _iso(STARTED + timedelta(seconds=1.7)),
         "content": "Artifact comment monitor for an artifact didn't resume: it couldn't restart in this session."},
    ]


def _registry():
    started_ms = int(STARTED.timestamp() * 1000)
    return parse_registry_record(
        {
            "pid": 4242, "sessionId": "conv-1", "cwd": "/example", "version": "2.1.322",
            "startedAt": started_ms, "procStart": "Tue Nov 10 23:24:46 2026", "kind": "interactive",
            "entrypoint": "cli", "tmux": "carnivore_example:@1.%1",
            "updatedAt": started_ms + 601, "status": "idle", "statusUpdatedAt": started_ms + 601,
        },
        path_pid=4242,
    )


def _verdict(queued_at: datetime, *, now: datetime = NOW):
    facts = classify_transcript_records(_records(queued_at), now=now)
    assert facts.queued_reinvoke is True
    return resolve_attention(Evidence(
        tmux_liveness=LIVENESS_LIVE, agent_family=FAMILY_CLAUDE, registry=_registry(),
        transcript=facts, pane=None, now=now, resting_prompt_held=True, identity=IDENTITY,
    ))


def test_a_notice_queued_before_the_restart_lets_the_session_rest():
    verdict = _verdict(QUEUED)
    assert (verdict.state, verdict.reason) == (STATE_DONE_IDLE, REASON_TURN_ENDED), verdict.detail


def test_a_notice_queued_after_this_process_started_still_reads_as_a_re_invoke():
    queued_after = STARTED + timedelta(minutes=5)
    verdict = _verdict(queued_after, now=queued_after + timedelta(seconds=30))
    assert (verdict.state, verdict.reason) == (STATE_BUSY, REASON_QUEUED_REINVOKE), verdict.detail

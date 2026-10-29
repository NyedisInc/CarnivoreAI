
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

from src.api.parked_work_listing import usage_limit_for
from src.core.attention.transcript_facts import classify_transcript_records

RESETS = 1792544400
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
NOTICE = (
    "<task-notification>\n<task-id>40df117fe6b10a1cf</task-id>\n"
    "<tool-use-id>toolu_012XrUU6cId5GkwhGduXW33j</tool-use-id>\n<status>failed</status>\n"
    "<summary>Agent \"H35\" failed: Agent terminated early due to an API error: "
    "You've hit your weekly limit (error type rate_limit, HTTP 429)</summary>\n</task-notification>"
)


def _turn_end(ts: str, pending: int) -> Dict[str, Any]:
    return {"type": "system", "subtype": "turn_duration", "isSidechain": False, "timestamp": ts,
            "version": "2.1.301", "pendingBackgroundAgentCount": pending}


def _limit_error(ts: str) -> Dict[str, Any]:
    info = {"status": "rejected", "resetsAt": RESETS, "rateLimitType": "seven_day"}
    return {"type": "assistant", "isSidechain": False, "timestamp": ts, "apiError": "usage_limit_reached",
            "apiErrorParams": {"rate_limit_info": info}, "quotaLimits": info, "error": "rate_limit",
            "isApiErrorMessage": True, "apiErrorStatus": 429,
            "message": {"model": "<synthetic>", "role": "assistant", "stop_reason": "stop_sequence",
                        "content": [{"type": "text", "text": "You've hit your weekly limit · resets Oct 20 at 9pm (America/New_York)"}]}}


def _normal_turn(ts: str) -> List[Dict[str, Any]]:
    return [{"type": "assistant", "isSidechain": False, "timestamp": ts,
             "message": {"model": "claude-sonnet-5-5", "role": "assistant",
                         "content": [{"type": "text", "text": "back"}]}},
            _turn_end(ts, 0)]


def _hit() -> List[Dict[str, Any]]:
    return [_turn_end("2026-10-17T06:17:46.670Z", 2), _limit_error("2026-10-17T06:20:00.279Z"),
            _turn_end("2026-10-17T06:20:00.282Z", 1),
            {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-10-17T06:21:06.341Z",
             "content": NOTICE}]


def _info_for(facts: Any) -> Any:
    observation = SimpleNamespace(stale=False, evidence=SimpleNamespace(transcript=facts, codex=None))
    watcher = SimpleNamespace(observation_for=lambda _id, now=None: observation)
    return watcher, SimpleNamespace(agent_family=None, session=SimpleNamespace(id="ses_1"))


def test_weekly_limit_published_and_dead_agent_not_work_then_cleared_by_a_normal_turn() -> None:
    facts = classify_transcript_records(_hit(), now=NOW)
    assert facts.usage_limit.kind == "weekly"
    assert facts.usage_limit.resets_at == datetime.fromtimestamp(RESETS, tz=timezone.utc)
    assert facts.queued_reinvoke is False
    assert facts.pending_background_agents is None
    watcher, info = _info_for(facts)
    row = usage_limit_for(watcher, info, NOW)
    assert (row.kind, row.resets_at, row.since) == (
        "weekly", "2026-10-21T01:00:00+00:00", "2026-10-17T06:20:00.279000+00:00")
    assert row.message.startswith("You've hit your weekly limit")
    assert usage_limit_for(watcher, info, datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)) is None
    cleared = classify_transcript_records(_hit() + _normal_turn("2026-10-17T07:00:00.000Z"), now=NOW)
    assert cleared.usage_limit is None
    assert usage_limit_for(*_info_for(cleared), NOW) is None

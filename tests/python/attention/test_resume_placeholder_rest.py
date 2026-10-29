
from __future__ import annotations

from typing import Any, Dict

from src.core.attention.transcript_facts import (
    FACTS_FOUND,
    classify_transcript_records,
)

SESSION = "42ca16a6-dc08-4b7a-bea1-1413f2b7e232"


def _turn_end(ts: str) -> Dict[str, Any]:
    return {"type": "system", "subtype": "turn_duration", "isSidechain": False,
            "durationMs": 6216, "timestamp": ts, "sessionId": SESSION,
            "version": "2.1.287", "pendingBackgroundAgentCount": 0}


def _assistant(ts: str, model: str, text: str, **extra: Any) -> Dict[str, Any]:
    record = {"type": "assistant", "isSidechain": False, "timestamp": ts,
              "sessionId": SESSION, "message": {
                  "model": model, "role": "assistant", "type": "message",
                  "content": [{"type": "text", "text": text}]}}
    record.update(extra)
    return record


def _tail(last_assistant: Dict[str, Any]) -> list:
    return [
        _assistant("2026-10-01T19:04:00.000Z", "claude-opus-4-7", "done"),
        _turn_end("2026-10-01T19:04:04.996Z"),
        {"type": "last-prompt", "sessionId": SESSION},
        last_assistant,
        {"type": "system", "subtype": "informational", "isSidechain": False,
         "timestamp": "2026-10-01T22:38:30.432Z", "sessionId": SESSION,
         "content": "Remote Control disconnected"},
        {"type": "system", "subtype": "local_command", "isSidechain": False,
         "timestamp": "2026-10-02T14:49:10.857Z", "sessionId": SESSION,
         "content": "<command-name>/remote-control</command-name>"},
    ]


def test_the_resume_placeholder_leaves_the_turn_at_rest_but_an_api_error_does_not():
    placeholder = _assistant("2026-10-01T19:26:07.900Z", "<synthetic>",
                             "No response requested.", isApiErrorMessage=False)
    facts = classify_transcript_records(_tail(placeholder))
    assert facts.verdict == FACTS_FOUND
    assert facts.pending_background_agents == 0
    assert facts.newest_assistant_at is not None
    assert facts.turn_end_at > facts.newest_assistant_at

    api_error = _assistant("2026-10-01T19:26:07.900Z", "<synthetic>",
                           "API Error: 500", isApiErrorMessage=True)
    facts = classify_transcript_records(_tail(api_error))
    assert facts.newest_assistant_at > facts.turn_end_at

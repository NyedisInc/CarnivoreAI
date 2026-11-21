
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import extract_line
from src.core.timeline.model import Kind

CONV = "c0000001-0000-4000-9000-000000000000"


def _assistant(stamp: str, msg: str, stop: str) -> Dict[str, Any]:
    return {"type": "assistant", "timestamp": stamp, "message": {
        "id": msg, "model": "m", "stop_reason": stop, "content": [{"type": "text", "text": "x"}]}}


def _turn_of_replies(records: List[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    ctx, offset, turns = ExtractContext(conv=CONV), 0, {}
    for record in records:
        raw = json.dumps(record, separators=(",", ":")).encode()
        offset += len(raw) + 1
        for event in extract_line(ctx, raw, offset):
            if event.kind is Kind.PROMPT:
                turns["prompt"] = event.turn
            elif event.kind is Kind.REPLY:
                turns[event.msg or ""] = event.turn
    return turns


def test_max_tokens_continues_the_turn_and_a_later_end_clears_that_memory() -> None:
    prompt = {"type": "user", "timestamp": "2026-11-01T10:00:00.000Z", "message": {"role": "user", "content": "go"}}
    duration = {"type": "system", "subtype": "turn_duration", "timestamp": "2026-11-01T10:00:09.000Z", "durationMs": 9000}
    continued = _turn_of_replies([prompt, _assistant("2026-11-01T10:00:01.000Z", "m1", "max_tokens"),
                                  _assistant("2026-11-01T10:00:02.000Z", "m2", "end_turn")])
    assert continued["m2"] == continued["prompt"] is not None
    ended = _turn_of_replies([prompt, _assistant("2026-11-01T10:00:01.000Z", "m1", "max_tokens"), duration,
                              _assistant("2026-11-01T10:00:10.000Z", "m3", "end_turn")])
    assert ended["m3"] is not None and ended["m3"] != ended["prompt"]

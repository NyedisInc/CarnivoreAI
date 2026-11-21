
from __future__ import annotations

import io
import json
from typing import Any, Dict, List

from src.core.session_token_usage.cache import TranscriptTotals
from src.core.session_token_usage.claude_reader import scan_lines


def _assistant(model: str, message_id: str, input_tokens: int) -> Dict[str, Any]:
    return {"type": "assistant", "message": {"id": message_id, "model": model, "role": "assistant", "content": [],
                                             "usage": {"input_tokens": input_tokens, "output_tokens": 0,
                                                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}}


def _scan(records: List[Dict[str, Any]]) -> TranscriptTotals:
    raw = b"".join(json.dumps(r).encode() + b"\n" for r in records)
    return scan_lines(io.BytesIO(raw), TranscriptTotals())[0]


def test_a_synthetic_turn_after_a_real_one_keeps_the_real_model():
    totals = _scan([_assistant("claude-opus-5-5", "m1", 1000), _assistant("<synthetic>", "m2", 0)])
    assert totals.last_model == "claude-opus-5-5"


def test_a_synthetic_turn_never_replaces_the_last_real_usage():
    totals = _scan([_assistant("claude-opus-5-5", "m1", 1000), _assistant("<synthetic>", "m2", 0)])
    assert totals.last_usage is not None and totals.last_usage["input_tokens"] == 1000


def test_a_transcript_of_only_synthetic_turns_stays_unknown():
    assert _scan([_assistant("<synthetic>", "m1", 0)]).last_model is None

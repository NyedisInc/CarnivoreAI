
from __future__ import annotations

import io
import json
from typing import Any, Dict, List, Optional

from src.core.session_token_usage.cache import TranscriptTotals
from src.core.session_token_usage.claude_reader import scan_lines
from src.core.session_token_usage.claude_selection import read_ultra_marker

_SESSION = "230b95e3-b238-400e-829c-f2814631a932"


def _local_effort(level: str, scope: str = "this session only") -> Dict[str, Any]:
    return {
        "type": "system",
        "subtype": "local_command",
        "content": (
            "<local-command-stdout>Set effort level to " + level + " ("
            + scope + "): <redacted></local-command-stdout>"
        ),
        "commandRun": {"command": "effort", "args": level},
        "level": "info",
        "isMeta": False,
        "sessionId": _SESSION,
        "timestamp": "2026-09-27T02:25:00.000Z",
    }


def _ultra(kind: str, reminder: Optional[str] = "full") -> Dict[str, Any]:
    attachment: Dict[str, Any] = {"type": "ultra_effort_" + kind}
    if reminder is not None:
        attachment["reminderType"] = reminder
    return {"type": "attachment", "attachment": attachment, "sessionId": _SESSION}


def _turn(effort: Optional[str], message_id: str) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "type": "assistant",
        "isSidechain": False,
        "sessionId": _SESSION,
        "message": {
            "id": message_id,
            "model": "claude-opus-5-5",
            "role": "assistant",
            "content": [{"type": "text", "text": "<redacted>"}],
            "usage": {"input_tokens": 3, "output_tokens": 5,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        },
    }
    if effort is not None:
        record["effort"] = effort
        record["perTurnEffort"] = effort
    return record


def _scan(records: List[Dict[str, Any]]) -> TranscriptTotals:
    raw = b"".join(json.dumps(r).encode() + b"\n" for r in records)
    totals, _ = scan_lines(io.BytesIO(raw), TranscriptTotals())
    return totals


def test_the_captured_ultracode_sequence_reports_ultracode_not_xhigh():
    totals = _scan([
        _turn("high", "m0"),
        _local_effort("ultracode"),
        _ultra("enter", "full"),
        _turn("xhigh", "m1"),
        _ultra("enter", "sparse"),
        _turn("xhigh", "m2"),
    ])
    assert totals.last_effort == "xhigh", "the turns themselves record xhigh"
    assert totals.effective_effort == "ultracode"


def test_an_enter_record_alone_latches_ultracode():
    totals = _scan([_turn("xhigh", "m1"), _ultra("enter", "full"), _turn("xhigh", "m2")])
    assert totals.effective_effort == "ultracode"


def test_the_exit_record_releases_the_latch_to_the_recorded_turn():
    totals = _scan([
        _ultra("enter", "full"), _turn("xhigh", "m1"),
        _ultra("exit", None), _turn("high", "m2"),
    ])
    assert totals.ultra_effort is False
    assert totals.effective_effort == "high"


def test_choosing_another_effort_releases_the_latch():
    totals = _scan([_local_effort("ultracode"), _ultra("enter"), _local_effort("max")])
    assert totals.effective_effort == "max"


def test_without_any_ultracode_record_the_turn_effort_stands():
    for level in ("low", "medium", "high", "xhigh", "max"):
        assert _scan([_turn(level, "m1")]).effective_effort == level


def test_an_unknown_effort_is_none_never_a_default():
    totals = _scan([_turn(None, "m1")])
    assert totals.last_usage is not None, "the turn was read"
    assert totals.effective_effort is None


def test_the_marker_reader_ignores_every_other_attachment():
    assert read_ultra_marker(_ultra("enter")) is True
    assert read_ultra_marker(_ultra("exit", None)) is False
    assert read_ultra_marker({"type": "attachment",
                              "attachment": {"type": "ultra_effort_misspelled"}}) is None
    assert read_ultra_marker({"type": "attachment", "attachment": {"type": "date"}}) is None
    assert read_ultra_marker(_turn("xhigh", "m1")) is None


def test_the_latch_survives_an_incremental_resume():
    first = _scan([_local_effort("ultracode"), _ultra("enter")])
    raw = json.dumps(_turn("xhigh", "m9")).encode() + b"\n"
    resumed, _ = scan_lines(io.BytesIO(raw), first)
    assert resumed.effective_effort == "ultracode"

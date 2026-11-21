
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.timeline.model import Kind, Pos, TimelineEvent

PLACEMENT = Path(__file__).resolve().parents[3] / "scripts" / "timeline" / "placement.py"
CONV = "c0000003-0000-4000-9000-000000000000"


def _load_placement() -> Any:
    spec = importlib.util.spec_from_file_location("timeline_placement_under_test", PLACEMENT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _event(kind: Kind, offset: int, n: int = 0, msg: Optional[str] = None, **data: Any) -> TimelineEvent:
    return TimelineEvent(pos=Pos(conv=CONV, offset=offset, serial="s"), n=n, turn=10, msg=msg, kind=kind, data=data)


def _counts(events: List[TimelineEvent]) -> Dict[str, int]:
    placement = _load_placement()
    counts = {key: 0 for key in ("replies", "replies_outside_turn", "replies_before_their_turn", "turns", "turns_with_end",
                                 "replies_after_primary_end", "replies_after_primary_end_of_closing_message",
                                 "replies_after_primary_end_in_reopened_turn")}
    placement.measure_events(events, counts)
    counts["unexplained"] = placement.unexplained(counts)
    return counts


def _turn(end_reason: str, between: List[TimelineEvent]) -> List[TimelineEvent]:
    return [_event(Kind.PROMPT, 10), _event(Kind.REPLY, 20, msg="a"),
            _event(Kind.TURN_END, 20, 1, via="stop_reason", end=end_reason), *between,
            _event(Kind.REPLY, 40, msg="b"), _event(Kind.TURN_END, 50, merged=True, via="duration")]


def test_a_reply_after_the_primary_end_is_exempt_only_for_a_named_reopen_cause() -> None:
    assert _counts(_turn("normal", []))["unexplained"] == 1
    assert _counts(_turn("max_tokens", []))["unexplained"] == 0
    assert _counts(_turn("normal", [_event(Kind.TOOL_CALL, 30, msg="a")]))["unexplained"] == 0
    assert _counts(_turn("normal", [_event(Kind.TOOL_CALL, 30, msg="c")]))["unexplained"] == 1

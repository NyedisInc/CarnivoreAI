
from __future__ import annotations

from typing import Any, Dict, List

from src.core.timeline.model import Kind, TimelineEvent
from tests.python.timeline.conftest import run_fixture


def _turns(manifest: Dict[str, Dict[str, Any]]) -> Dict[int, List[TimelineEvent]]:
    grouped: Dict[int, List[TimelineEvent]] = {}
    for _record, events in run_fixture(manifest["continue_cases"]):
        for event in events:
            if event.turn is not None:
                grouped.setdefault(event.turn, []).append(event)
    return grouped


def test_a_tool_use_record_of_the_closing_message_keeps_the_turn_open(manifest: Dict[str, Dict[str, Any]]) -> None:
    first = next(iter(_turns(manifest).values()))
    kinds = [e.kind for e in first]
    assert Kind.TOOL_CALL in kinds and Kind.TOOL_RESULT in kinds
    assert [e.msg for e in first if e.kind is Kind.REPLY] == ["msg_split_tool", "msg_after_tool"]
    ends = [e for e in first if e.kind is Kind.TURN_END]
    assert [e.data.get("merged") for e in ends] == [None, True]


def test_a_max_tokens_stop_followed_by_an_assistant_message_continues_the_turn(
        manifest: Dict[str, Dict[str, Any]]) -> None:
    second = list(_turns(manifest).values())[1]
    assert [e.msg for e in second if e.kind is Kind.REPLY] == ["msg_cut", "msg_resumed"]


def test_every_turn_of_the_fixture_opens_with_a_prompt(manifest: Dict[str, Dict[str, Any]]) -> None:
    turns = _turns(manifest)
    assert len(turns) == 3 and all(t[0].kind is Kind.PROMPT for t in turns.values())

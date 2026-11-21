
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from src.core.flow_data.collect.transcript import ENVELOPE_RE
from src.core.swarm.owner_message import REF_LINE
from src.core.timeline import prompts
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import extract_line
from src.core.timeline.model import Kind, Pos, TimelineEvent
from tests.python.timeline.conftest import run_fixture


def _kinds(manifest: Dict[str, Dict[str, Any]], name: str) -> List[str]:
    return [event.kind.value for _record, events in run_fixture(manifest[name]) for event in events]


def test_a_plain_turn_reads_prompt_work_reply_and_one_primary_turn_end(manifest: Dict[str, Dict[str, Any]]) -> None:
    events = [e for _r, es in run_fixture(manifest["basic_turns"]) for e in es]
    first_turn = [e for e in events if e.turn == events[1].turn]
    assert [e.kind.value for e in first_turn][:3] == ["prompt", "thinking", "reply"]
    ends = [e for e in first_turn if e.kind is Kind.TURN_END]
    assert [(e.data["via"], e.data.get("merged", False)) for e in ends] == [
        ("stop_reason", False), ("stop_hook", True), ("duration", True)]
    assert ends[-1].data["pending_agents"] == 0 and ends[-1].data["duration_ms"] == 1500


def test_thinking_is_counted_never_stored(manifest: Dict[str, Dict[str, Any]]) -> None:
    thoughts = [e for _r, es in run_fixture(manifest["basic_turns"]) for e in es if e.kind is Kind.THINKING]
    assert [e.data for e in thoughts] == [{"chars": len("fixture thought")}]


def test_a_queued_message_is_a_queue_event_then_a_queued_prompt(manifest: Dict[str, Dict[str, Any]]) -> None:
    kinds = _kinds(manifest, "queue_cases")
    assert kinds[2:6] == ["queue", "queue", "tool_result", "prompt"]
    prompts_seen = [e for _r, es in run_fixture(manifest["queue_cases"]) for e in es if e.kind is Kind.PROMPT]
    assert [e.data["origin"] for e in prompts_seen] == ["human", "queued", "human"]


def test_the_paste_wrapper_is_unwrapped_for_classification(manifest: Dict[str, Dict[str, Any]]) -> None:
    events = [e for _r, es in run_fixture(manifest["paste_cases"]) for e in es if e.kind is Kind.PROMPT]
    assert events[0].data["wrapped"] is True and events[0].data["plain"] is True
    assert "wrapped" not in events[1].data
    body, wrapped = prompts.unwrap_pasted('typed\n\n<pasted_content id="ab12">\nbody\n</pasted_content id="ab12">\n')
    assert (body, wrapped) == ("typed\n\nbody", True)


def test_interrupts_end_the_turn_and_a_max_tokens_stop_says_so(manifest: Dict[str, Dict[str, Any]]) -> None:
    ends = [e.data for _r, es in run_fixture(manifest["interrupt_cases"]) for e in es if e.kind is Kind.TURN_END]
    assert [(d["via"], d["end"]) for d in ends] == [("interrupt", "interrupted")] * 2 + [("stop_reason", "max_tokens")]


def test_an_agent_launch_and_its_notice_pair_up(manifest: Dict[str, Dict[str, Any]]) -> None:
    kinds = _kinds(manifest, "agent_main")
    assert "subagent_start" in kinds and "subagent_end" in kinds and "bg_end" not in kinds
    sub = [e for _r, es in run_fixture(manifest["agent_sub"]) for e in es]
    assert {e.thread for e in sub} == {"agent:a1fixture"}
    assert sub[-1].data == {"agent_id": "a1fixture", "tool_use_id": "toolu_a1", "status": "completed", "via": "structured_output"}


def test_a_fork_head_is_one_switch_and_a_continuation_another(manifest: Dict[str, Dict[str, Any]]) -> None:
    switches = [e.data["how"] for _r, es in run_fixture(manifest["switch_cases"]) for e in es if e.kind is Kind.CONVERSATION_SWITCH]
    assert switches == ["fork", "continued"]


def test_a_compaction_summary_points_at_its_boundary(manifest: Dict[str, Dict[str, Any]]) -> None:
    events = [e for _r, es in run_fixture(manifest["compaction_cases"]) for e in es if e.kind is Kind.COMPACTION]
    assert events[1].data == {"phase": "summary"} and events[1].parent == events[0].id


def test_a_line_over_the_budget_is_one_stub_that_is_not_parsed() -> None:
    ctx = ExtractContext(conv="c1")
    raw = b'{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_big","content":"' + b"x" * 300 + b'"}]}}'
    events = extract_line(ctx, raw, 999, serial="s1", max_bytes=100)
    assert [(e.kind, e.data) for e in events] == [
        (Kind.TOOL_RESULT, {"tool_use_id": "toolu_big", "bytes": len(raw), "oversize": True})]
    other = extract_line(ctx, b'{"type":"mystery",' + b"y" * 200 + b"}", 1500, serial="s2", max_bytes=100)
    assert [(e.kind, e.data["record_type"]) for e in other] == [(Kind.UNKNOWN, "mystery")]


def test_a_broken_line_is_unknown_not_an_exception() -> None:
    events = extract_line(ExtractContext(conv="c1"), b"{not json", 9, serial="s")
    assert [e.data["record_type"] for e in events] == ["not-json"]


def test_the_model_refuses_text_and_undeclared_keys() -> None:
    pos = Pos(conv="c", offset=1, serial="s")
    with pytest.raises(ValidationError):
        TimelineEvent(pos=pos, kind=Kind.REPLY, data={"text": "hello"})
    with pytest.raises(ValidationError):
        TimelineEvent(pos=pos, kind=Kind.SUPPRESSED, data={"cause": "x" * 500})


def test_the_event_id_is_derived_from_the_position() -> None:
    event = TimelineEvent(pos=Pos(conv="c", file_key="a1", offset=12, serial="sha256:0123456789"), n=2, kind=Kind.UNKNOWN)
    assert event.id == "c:a1:12:2:01234567"


def test_origins_follow_their_markers_and_match_the_live_patterns() -> None:
    assert ENVELOPE_RE.pattern == prompts.ENVELOPE_RE.pattern
    assert prompts.prompt_origin({}, "hi\n" + REF_LINE.format(ref="huddle:msg:7")) == "swarm"
    assert prompts.prompt_origin({}, "thread t-1 msg m-2\nhello") == "crosstalk"
    assert prompts.prompt_origin({"origin": {"kind": "channel"}}, "x") == "channel"
    assert prompts.prompt_origin({}, "[thu 10/09 14:02, 2h ago] hi") == "messaging"
    assert prompts.prompt_origin({}, "<command-message>x</command-message>") == "other_tag"
    assert prompts.prompt_origin({}, "plain words") == "human"
    assert json.dumps(prompts.attachment_kinds({"message": {"content": [{"type": "image"}, {"type": "text"}]}})) == '["image"]'


from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from src.core.timeline import mapping
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import extract_line
from src.core.timeline.model import Kind, Pos, TimelineEvent
from src.core.timeline.oversize import OversizeSerialError, scan_head
from src.core.transcript_contract.claude_attachment_kinds import ATTACHMENT_KINDS

WRAP = '\n\n<pasted_content id="ab12">\nhello there\n</pasted_content id="ab12">\n'


def _feed(ctx: ExtractContext, *records: Dict[str, Any], max_bytes: int = 1 << 20) -> List[TimelineEvent]:
    events: List[TimelineEvent] = []
    for number, record in enumerate(records, start=1):
        raw = json.dumps(record).encode()
        events += extract_line(ctx, raw, number * 1000, serial=f"s{number}", max_bytes=max_bytes)
    return events


def _user(text: Any, **extra: Any) -> Dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": text}, **extra}


def test_an_oversize_attachment_file_line_gives_no_event() -> None:
    raw = (b'{"parentUuid":"p","isSidechain":false,"attachment":{"type":"file","filename":"a.pdf","content":"'
           + b"x" * 5000 + b'"},"type":"attachment","uuid":"u1"}')
    assert extract_line(ExtractContext(conv="c"), raw, 9, serial="u1", max_bytes=100) == []


def test_an_oversize_api_request_blob_gives_no_event() -> None:
    raw = b'{"type":"api-request-blob","hash":"h","message":{"content":"' + b"y" * 5000 + b'"}}'
    assert extract_line(ExtractContext(conv="c"), raw, 9, serial="h", max_bytes=100) == []


def test_an_oversize_unknown_kind_still_shows_as_unknown_with_its_key_parts() -> None:
    raw = b'{"type":"attachment","attachment":{"type":"zz_new_kind","body":"' + b"y" * 5000 + b'"}}'
    (event,) = extract_line(ExtractContext(conv="c"), raw, 9, serial="s", max_bytes=100)
    assert event.kind is Kind.UNKNOWN
    assert event.data == {"record_type": "attachment", "attachment_type": "zz_new_kind", "bytes": len(raw), "oversize": True}


def test_scan_head_takes_the_records_own_type_not_the_first_one() -> None:
    head = '{"message":{"content":[{"type":"tool_result","content":"a \\"type\\": \\"x\\""}]},"type":"user","subtype":"s"}'
    assert scan_head(head) == {"type": "user", "subtype": "s"}
    assert scan_head('{"attachment":{"type":"file"},"type":"attachment"}') == {"attachment_type": "file", "type": "attachment"}


def test_an_oversize_line_without_a_serial_is_refused_not_parsed() -> None:
    with pytest.raises(OversizeSerialError):
        extract_line(ExtractContext(conv="c"), b'{"type":"user"}' + b" " * 300, 9, max_bytes=100)


def test_a_wrapped_enqueue_is_plain_with_the_bodys_length() -> None:
    (event,) = _feed(ExtractContext(conv="c"), {"type": "queue-operation", "operation": "enqueue", "content": WRAP})
    assert event.data["plain"] is True and event.data["wrapped"] is True and event.data["chars"] == len("hello there")
    (prompt,) = _feed(ExtractContext(conv="c"), _user(WRAP))
    assert prompt.data["plain"] is True and prompt.data["chars"] == event.data["chars"]


def test_a_harness_generated_prompt_is_not_a_human_one() -> None:
    (event,) = _feed(ExtractContext(conv="c"), _user("auto wakeup text", promptSource="system"))
    assert (event.data["origin"], event.data["plain"]) == ("system", False)
    (other,) = _feed(ExtractContext(conv="c"), _user("hello", origin={"kind": "coordinator"}))
    assert (other.data["origin"], other.data["plain"]) == ("other", False)
    (human,) = _feed(ExtractContext(conv="c"), _user("hello", origin={"kind": "human"}, promptSource="typed"))
    assert (human.data["origin"], human.data["plain"]) == ("human", True)


@pytest.mark.parametrize("text, end", [("API Error: 500 boom", "error"), ("You have hit your usage limit", "usage_limit")])
def test_an_api_error_record_ends_the_turn(text: str, end: str) -> None:
    error = {"type": "assistant", "isApiErrorMessage": True, "message": {
        "model": "<synthetic>", "stop_reason": "stop_sequence", "content": [{"type": "text", "text": text}]}}
    events = _feed(ExtractContext(conv="c"), _user("go on"), error)
    assert [e.kind for e in events] == [Kind.PROMPT, Kind.NOTICE, Kind.TURN_END]
    assert events[2].data["end"] == end and events[2].turn == events[0].turn


@pytest.mark.parametrize("stamp", [{"origin": {"kind": "task-notification"}, "version": "2.1.150"}, {"version": "2.1.90"}],
                         ids=["origin-carrying", "origin-less-old-release"])
def test_a_notice_for_an_unseen_task_does_not_invent_a_kind(stamp: Dict[str, Any]) -> None:
    notice = ("<task-notification><task-id>a9</task-id><status>completed</status></task-notification>")
    events = _feed(ExtractContext(conv="c"), _user(notice, **stamp))
    (end,) = [e for e in events if e.kind in (Kind.BG_END, Kind.SUBAGENT_END)]
    assert end.kind is Kind.BG_END and "bg_kind" not in end.data


def test_a_fork_head_teaches_the_context_without_events() -> None:
    ctx = ExtractContext(conv="c")
    inherited = {"type": "assistant", "forkedFrom": {"sessionId": "src"}, "message": {"content": [
        {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}]}}
    stray = {"type": "system", "subtype": "turn_duration", "forkedFrom": {"sessionId": "src"}, "durationMs": 5}
    result = _user([{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}])
    events = _feed(ctx, inherited, stray, result)
    assert [e.kind for e in events] == [Kind.CONVERSATION_SWITCH, Kind.TOOL_RESULT]
    assert events[1].data["name"] == "Bash" and events[1].parent is None


def test_the_named_gaps_are_never_unknown() -> None:
    keys = ["attachment||session_cron_carry", "attachment||ultra_effort_enter", "attachment||ultra_effort_exit",
            "attachment||workflow_keyword_request", "attachment||peer_mention", "failed||", "fork-context-ref||",
            "system|agents_killed|", "progress||", "api-request-blob||", "file-history-snapshot||",
            "artifact-comment-monitor||", "started||", "result||", "launched||"]
    assert [key for key in keys if mapping.classify(key) == mapping.UNKNOWN_CLASS] == []


def test_every_contract_attachment_kind_is_decided() -> None:
    mapped = {key.split("||")[1] for key in mapping.MAPPED if key.startswith("attachment||")}
    assert set(ATTACHMENT_KINDS) - mapped - mapping.IGNORED_ATTACHMENT_KINDS == set()
    assert not mapping.IGNORED_ATTACHMENT_KINDS - set(ATTACHMENT_KINDS)


def test_the_model_refuses_a_bad_thread_family_and_nested_value() -> None:
    pos = Pos(conv="c", offset=1, serial="s")
    with pytest.raises(ValidationError):
        TimelineEvent(pos=pos, kind=Kind.THINKING, family="gemini")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        TimelineEvent(pos=pos, kind=Kind.THINKING, thread="agent:")
    with pytest.raises(ValidationError):
        TimelineEvent(pos=pos, kind=Kind.THINKING, data={"chars": {"n": 1}})
    with pytest.raises(ValidationError):
        TimelineEvent(pos=pos, kind=Kind.PROMPT, data={"attachments": [["x"]]})
    assert TimelineEvent(pos=pos, kind=Kind.PROMPT, thread="wf:abc", data={"attachments": ["image"]}).thread == "wf:abc"

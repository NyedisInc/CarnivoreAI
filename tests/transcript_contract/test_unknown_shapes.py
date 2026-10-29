
from __future__ import annotations

import json

import pytest

from src.core.transcript_contract import UnknownRecord, parse_claude_line, parse_codex_line
from src.core.transcript_contract.claude_blocks import UnknownBlock
from tests.transcript_contract.fixture_lines import load

ASSISTANT = json.loads(next(r for r in load("claude") if r["shape"] == "record:assistant")["line"])


def _keys(parsed) -> set:
    return {f.key() for f in parsed.findings}


def _assistant(**changes) -> str:
    obj = json.loads(json.dumps(ASSISTANT))
    obj["message"].update(changes)
    return json.dumps(obj)


def test_unknown_record_type_is_carried_and_counted() -> None:
    line = '{"type":"brand-new-record","sessionId":"<str>","x":1}'
    parsed = parse_claude_line(line)
    assert parsed.status == "ok" and not parsed.known and parsed.kind == "brand-new-record"
    assert isinstance(parsed.record, UnknownRecord) and parsed.record.raw == json.loads(line)
    assert _keys(parsed) == {"unknown_type:record:brand-new-record"}
    assert parsed.text == line


def test_unknown_block_extra_key_and_type_mismatch() -> None:
    parsed = parse_claude_line(_assistant(content=[{"type": "text", "text": "<str>"},
                                                   {"type": "hologram", "beam": 1}],
                                          novelField=True, stop_reason=7))
    blocks = parsed.record.message.content
    assert isinstance(blocks[1], UnknownBlock) and blocks[1].type == "hologram"
    assert parsed.record.message.stop_reason is None
    assert parsed.raw["message"]["stop_reason"] == 7
    assert {"unknown_type:block:assistant:hologram", "extra_key:message.novelField",
            "type_mismatch:message.stop_reason:integer"} <= _keys(parsed)


def test_content_that_stopped_being_an_array_is_reported() -> None:
    parsed = parse_claude_line(_assistant(content={"type": "text"}))
    assert parsed.record.message.content is None
    assert "type_mismatch:message.content:object" in _keys(parsed)


def test_missing_required_and_unknown_discriminators() -> None:
    no_uuid = dict(ASSISTANT)
    no_uuid.pop("uuid")
    assert "missing_required:uuid" in _keys(parse_claude_line(json.dumps(no_uuid)))
    system = parse_claude_line('{"type":"system","subtype":"warp_drive"}')
    assert "unknown_type:system_subtype:warp_drive" in _keys(system) and system.known
    queue = parse_claude_line('{"type":"queue-operation","operation":"teleport"}')
    assert "unknown_type:queue_operation:teleport" in _keys(queue)
    attach = parse_claude_line('{"type":"attachment","attachment":{"type":"telepathy"}}')
    assert "unknown_type:attachment_kind:telepathy" in _keys(attach)
    assert attach.record.attachment.known is False


def test_codex_unknown_payload_and_line_type() -> None:
    parsed = parse_codex_line('{"timestamp":"t","type":"event_msg","payload":{"type":"quantum"}}')
    assert parsed.kind == "event_msg:quantum" and not parsed.known
    assert isinstance(parsed.record.payload, UnknownRecord)
    assert _keys(parsed) == {"unknown_type:codex_payload:event_msg:quantum"}
    line = parse_codex_line('{"timestamp":"t","type":"hyperspace","payload":{}}')
    assert "unknown_type:codex_line:hyperspace" in _keys(line)


@pytest.mark.parametrize("text,status", [
    ("\n", "blank"), ("   ", "blank"), ("{not json", "unparseable"),
    ("[1,2]", "non_object"), ("42", "non_object"), ('"s"', "non_object"),
])
def test_non_records_keep_their_status(text: str, status: str) -> None:
    for parse in (parse_claude_line, parse_codex_line):
        parsed = parse(text)
        assert parsed.status == status and parsed.record is None and parsed.text == text


@pytest.mark.parametrize("obj", [
    {"type": "assistant", "message": "a string"},
    {"type": "user", "message": {"content": {"odd": 1}}},
    {"type": "user", "message": {"role": "user", "content": [1, None, "x", []]}},
    {"type": 5},
    {"type": "attachment", "attachment": {"type": 3}},
    {"type": "assistant", "message": {"content": [{"type": "tool_result", "content": {}}]}},
])
def test_garbage_never_raises(obj: dict) -> None:
    parsed = parse_claude_line(json.dumps(obj))
    assert parsed.status == "ok" and parsed.findings

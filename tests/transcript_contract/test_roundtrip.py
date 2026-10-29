
from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from src.core.transcript_contract import (
    CLAUDE_RECORD_TYPES,
    QUEUE_OPERATIONS,
    SYSTEM_SUBTYPES,
    parse_claude_line,
    parse_codex_line,
)
from src.core.transcript_contract.claude_attachment_kinds import ATTACHMENT_KINDS
from src.core.transcript_contract.claude_blocks import (
    ImageBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from src.core.transcript_contract.codex_records import CodexLine, EvTokenCount, TokenCountInfo
from src.core.transcript_contract.fields import specs_of
from tests.transcript_contract.fixture_lines import load

CLAUDE = load("claude")
CODEX = load("codex")


def _read_back(record: Any, raw: Any) -> int:
    checked = 0
    for attr, spec in specs_of(type(record)):
        value = getattr(record, attr)
        if spec.json not in raw:
            assert value is None, attr
            continue
        checked += 1
        expected = raw[spec.json]
        if dataclasses.is_dataclass(value):
            checked += _read_back(value, expected)
        elif isinstance(value, tuple):
            assert len(value) == len(expected), attr
            for item, item_raw in zip(value, expected):
                if dataclasses.is_dataclass(item) and hasattr(item, "raw"):
                    assert item.raw is item_raw
                elif dataclasses.is_dataclass(item):
                    checked += _read_back(item, item_raw)
        elif hasattr(value, "raw"):
            assert value.raw is expected, attr
        else:
            assert value == expected, attr
    return checked


@pytest.mark.parametrize("row", CLAUDE, ids=[r["shape"] for r in CLAUDE])
def test_claude_fixture_round_trips(row: dict) -> None:
    parsed = parse_claude_line(row["line"])
    assert parsed.clean, [f.key() for f in parsed.findings]
    assert parsed.text == row["line"]
    assert _read_back(parsed.record, parsed.raw) >= 2


@pytest.mark.parametrize("row", CODEX, ids=[r["shape"] for r in CODEX])
def test_codex_fixture_round_trips(row: dict) -> None:
    parsed = parse_codex_line(row["line"])
    assert parsed.clean, [f.key() for f in parsed.findings]
    line = parsed.record
    assert isinstance(line, CodexLine)
    raw = parsed.raw.get("payload", parsed.raw)
    if hasattr(line.payload, "raw"):
        assert line.payload.raw is raw
    else:
        assert _read_back(line.payload, raw) >= 1


def test_fixtures_cover_every_declared_claude_shape() -> None:
    shapes = {r["shape"] for r in CLAUDE}
    for kind in CLAUDE_RECORD_TYPES:
        assert f"record:{kind}" in shapes or kind == "attachment", kind
    assert {f"system:{s}" for s in SYSTEM_SUBTYPES} <= shapes
    assert {f"queue_operation:{op}" for op in QUEUE_OPERATIONS} <= shapes
    assert {f"attachment:{k}" for k in ATTACHMENT_KINDS} <= shapes
    for name in ("block:assistant:text", "block:assistant:thinking", "block:assistant:tool_use",
                 "block:assistant:fallback", "block:user:tool_result", "block:user:image",
                 "block:user:document", "tool_result_item:tool_reference", "user:content_string"):
        assert name in shapes


def test_typed_values_are_the_line_values() -> None:
    tool_use = next(r for r in CLAUDE if r["shape"] == "block:assistant:tool_use")
    rec = parse_claude_line(tool_use["line"]).record
    block = rec.message.content[0]
    assert isinstance(block, ToolUseBlock) and block.id == "<str>" and block.input == {}
    assert rec.message.usage.input_tokens == 0 and rec.version == "<str>"

    image_item = next(r for r in CLAUDE if r["shape"] == "tool_result_item:image")
    result = parse_claude_line(image_item["line"]).record.message.content[0]
    assert isinstance(result, ToolResultBlock) and isinstance(result.content[0], ImageBlock)
    assert result.content[0].source.type == "base64"

    queued = next(r for r in CLAUDE if r["shape"] == "attachment:queued_command")
    body = parse_claude_line(queued["line"]).record.attachment
    assert body.known and body.queued_command is not None
    assert body.queued_command.prompt == body.raw["prompt"]

    string_user = next(r for r in CLAUDE if r["shape"] == "user:content_string")
    assert parse_claude_line(string_user["line"]).record.message.content == "<str>"

    plain = parse_claude_line(next(r for r in CLAUDE if r["shape"] == "record:user")["line"])
    assert isinstance(plain.record.message.content[0], TextBlock)

    token = next(r for r in CODEX if r["shape"] == "event_msg:token_count")
    payload = parse_codex_line(token["line"]).record.payload
    assert isinstance(payload, EvTokenCount) and isinstance(payload.info, TokenCountInfo)
    assert payload.info.total_token_usage == {}


from __future__ import annotations

import json
from typing import Any, BinaryIO, Iterator, List, Optional, Tuple

from src.core.transcript_contract.claude_blocks import ToolResultBlock
from src.core.transcript_contract.claude_attachments import AttachmentBody, parse_attachment_body
from src.core.transcript_contract.claude_message import UserMessage, parse_user_message
from src.core.transcript_contract.claude_meta_records import QueueOperationRecord
from src.core.transcript_contract.claude_parse import parse_claude_obj
from src.core.transcript_contract.fields import Report, bind
from src.core.transcript_contract.parsed import ParsedLine

_NEWLINE = b"\n"


def decode_json(raw: bytes) -> Tuple[bool, Any]:
    try:
        return True, json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return False, None


def decode_object(raw: bytes) -> Optional[dict]:
    ok, value = decode_json(raw)
    return value if ok and isinstance(value, dict) else None


def typed_record(record: dict) -> ParsedLine:
    return parse_claude_obj(record)


def user_message(record: dict) -> Optional[UserMessage]:
    if record.get("type") != "user":
        return None
    message = record.get("message")
    return parse_user_message(message, "message.", Report()) if isinstance(message, dict) else None


def tool_result_blocks(record: dict) -> Tuple[ToolResultBlock, ...]:
    if record.get("type") != "user":
        return ()
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return ()
    report = Report()
    return tuple(bind(ToolResultBlock, item, "message.content[tool_result].", report)
                 for item in content
                 if isinstance(item, dict) and item.get("type") == "tool_result")


def queue_operation(record: dict) -> Optional[QueueOperationRecord]:
    if record.get("type") != "queue-operation":
        return None
    return bind(QueueOperationRecord, record, "", Report())


def attachment_body(record: dict) -> Optional[AttachmentBody]:
    if record.get("type") != "attachment":
        return None
    body = record.get("attachment")
    return parse_attachment_body(body, "attachment.", Report()) if isinstance(body, dict) else None


def complete_lines(chunk: bytes, *, at_start: bool) -> List[bytes]:
    pieces = chunk.split(_NEWLINE)
    if not at_start:
        pieces = pieces[1:]
    pieces = pieces[:-1] if pieces else pieces
    return [piece for piece in pieces if piece.strip()]


class LineScan:

    def __init__(self, handle: BinaryIO, marks: Tuple[bytes, ...] = (),
                 rejects: Tuple[bytes, ...] = ()) -> None:
        self._handle = handle
        self._marks = marks
        self._rejects = rejects
        self.offset: int = handle.tell()
        self.hit: bytes = b""

    def __iter__(self) -> Iterator[bytes]:
        marks = self._marks
        if self._rejects or len(marks) > 2:
            return self._iter_general()
        if len(marks) == 2:
            return self._iter_two(marks[0], marks[1])
        return self._iter_one(marks[0] if marks else b"")

    def _iter_one(self, mark: bytes) -> Iterator[bytes]:
        readline = self._handle.readline
        offset = self.offset
        while True:
            line = readline()
            if not line or not line.endswith(_NEWLINE):
                self.offset = offset
                return
            offset += len(line)
            if mark in line:
                self.offset = offset
                self.hit = mark
                yield line

    def _iter_two(self, first: bytes, second: bytes) -> Iterator[bytes]:
        readline = self._handle.readline
        offset = self.offset
        while True:
            line = readline()
            if not line or not line.endswith(_NEWLINE):
                self.offset = offset
                return
            offset += len(line)
            if first in line:
                self.hit = first
            elif second in line:
                self.hit = second
            else:
                continue
            self.offset = offset
            yield line

    def _iter_general(self) -> Iterator[bytes]:
        readline = self._handle.readline
        marks, rejects = self._marks, self._rejects
        offset = self.offset
        while True:
            line = readline()
            if not line or not line.endswith(_NEWLINE):
                self.offset = offset
                return
            offset += len(line)
            if marks and not any(mark in line for mark in marks):
                continue
            if rejects and any(reject in line for reject in rejects):
                continue
            self.offset = offset
            yield line

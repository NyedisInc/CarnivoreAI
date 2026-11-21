
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.core.timeline import cursor as cursors
from src.core.timeline.context import ExtractContext
from src.core.timeline.extract import MAX_LINE_BYTES, extract_line
from src.core.timeline.model import FAMILY_CLAUDE, SERIAL_HASH_PREFIX, SERIAL_ID_CHARS, Kind, TimelineEvent
from src.core.transcript_manifest.tail import line_serial

MAX_BODY_CHARS: int = 64 * 1024
OVERSIZE_MARGIN_CHARS: int = 16 * 1024
_BYTES_PER_CHAR: int = 4
_WINDOW_GROWTH: int = 4
MAX_WINDOW_BYTES: int = 32 * 1024 * 1024
_ID_RE = re.compile(r"\A([^\s:]{1,120}):([^\s:]{1,120}):(\d{1,15}):(\d{1,4}):([^\s:]{1,16})\Z")


class EventIdError(ValueError):
    pass


class StaleEvent(LookupError):
    pass


@dataclass(frozen=True)
class EventId:

    conv: str
    file_key: str
    offset: int
    n: int
    serial8: str


def parse_event_id(text: str) -> EventId:
    found = _ID_RE.match(text)
    if found is None:
        raise EventIdError("an event id is <conv>:<file_key>:<offset>:<n>:<serial8>")
    return EventId(found.group(1), found.group(2), int(found.group(3)), int(found.group(4)), found.group(5))


def _blocks(record: Dict[str, Any]) -> list:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(item.get("text", "") for item in value if isinstance(item, dict) and isinstance(item.get("text"), str))
    return json.dumps(value, separators=(",", ":")) if value is not None else ""


def _kind_text(event: TimelineEvent, record: Dict[str, Any]) -> Optional[str]:
    from src.core.attention.transcript_records import record_text  # noqa: PLC0415

    kind, call_id = event.kind, event.data.get("tool_use_id")
    if kind in (Kind.PROMPT, Kind.COMMAND, Kind.REPLY):
        return record_text(record)
    if kind is Kind.QUEUE:
        content = record.get("content")
        return content if isinstance(content, str) else record_text(record)
    blocks = _blocks(record)
    if kind is Kind.TOOL_CALL:
        call = next((b for b in blocks if b.get("type") == "tool_use" and b.get("id") == call_id), None)
        return json.dumps(call.get("input"), separators=(",", ":")) if call else None
    if kind is Kind.TOOL_RESULT:
        result = next((b for b in blocks if b.get("type") == "tool_result" and b.get("tool_use_id") == call_id), None)
        return _flatten(result.get("content")) if result else None
    return None


def _clean(text: str) -> tuple:
    from src.core.cross_session_search import strip_ansi  # noqa: PLC0415
    from src.core.stream_redactor import redact_whole  # noqa: PLC0415

    redacted = redact_whole(strip_ansi(text))
    return redacted[:MAX_BODY_CHARS], len(redacted) > MAX_BODY_CHARS


def clean_prefix(body_bytes: bytes) -> tuple:
    from src.core.cross_session_search import strip_ansi  # noqa: PLC0415
    from src.core.stream_redactor import redact_whole  # noqa: PLC0415

    need = MAX_BODY_CHARS + OVERSIZE_MARGIN_CHARS
    limit = min(len(body_bytes), MAX_WINDOW_BYTES)
    window = min(limit, need * _BYTES_PER_CHAR)
    while True:
        stripped = strip_ansi(body_bytes[:window].decode("utf-8", "ignore"))
        if len(stripped) >= need or window >= limit:
            break
        window = min(limit, window * _WINDOW_GROWTH)
    redacted = redact_whole(stripped)
    if window >= len(body_bytes):
        return redacted[:MAX_BODY_CHARS], len(redacted) > MAX_BODY_CHARS
    return redacted[:max(0, min(MAX_BODY_CHARS, len(redacted) - OVERSIZE_MARGIN_CHARS))], True


def read_body(real: str, ident: EventId, family: str = FAMILY_CLAUDE) -> Dict[str, Any]:
    start = cursors.line_start_before(real, ident.offset)
    if start is None:
        raise StaleEvent("no line ends at that offset any more")
    with open(real, "rb") as handle:
        handle.seek(start)
        raw = handle.read(ident.offset - start)
    if len(raw) != ident.offset - start:
        raise StaleEvent("the file is shorter than the id says")
    body_bytes = raw[:-1]
    serial = line_serial(body_bytes)
    if serial.removeprefix(SERIAL_HASH_PREFIX)[:SERIAL_ID_CHARS] != ident.serial8:
        raise StaleEvent("the line at that offset is not the one the id names")
    events = extract_line(ExtractContext(conv=ident.conv, file_key=ident.file_key, family=family), body_bytes, ident.offset, serial=serial)
    if ident.n >= len(events):
        raise StaleEvent("that line does not make that many events")
    event = events[ident.n]
    base = {"event": event, "bytes": len(body_bytes), "withheld": None}
    if event.kind is Kind.THINKING:
        return {**base, "body": None, "truncated": False, "withheld": "thinking"}
    if len(body_bytes) > MAX_LINE_BYTES:
        text, cut = clean_prefix(body_bytes)
        return {**base, "body": text, "truncated": cut}
    record = json.loads(body_bytes)
    text = _kind_text(event, record) if isinstance(record, dict) else None
    text, cut = _clean(text if text is not None else body_bytes.decode("utf-8", "replace"))
    return {**base, "body": text, "truncated": cut}

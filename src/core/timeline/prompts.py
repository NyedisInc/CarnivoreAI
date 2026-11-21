
from __future__ import annotations

import re
from typing import Any, List, Mapping, Optional, Tuple

from src.core.attention.transcript_records import (
    SYSTEM_PROMPT_SOURCE,
    TASK_NOTIFICATION_MARKER,
    is_task_notification,
)
from src.core.flow_data.collect.transcript import ENVELOPE_RE

ORIGIN_HUMAN, ORIGIN_QUEUED, ORIGIN_CHANNEL = "human", "queued", "channel"
ORIGIN_CROSSTALK, ORIGIN_SWARM, ORIGIN_MESSAGING = "crosstalk", "swarm", "messaging"
ORIGIN_OTHER_TAG = "other_tag"
ORIGIN_SYSTEM, ORIGIN_OTHER = "system", "other"

ORIGIN_KIND_CHANNEL: str = "channel"
ORIGIN_KIND_PEER: str = "peer"
ORIGIN_KIND_HUMAN: str = "human"
ORIGIN_KIND_TASK_NOTICE: str = "task-notification"
ORIGIN_FIRST_VERSION: Tuple[int, ...] = (2, 1, 111)

ENVELOPE_WINDOW: int = 600

OWNER_REF_RE = re.compile(r"\(owner_message_ref=[^)]*\)")

MESSAGING_HEADER_RE = re.compile(r"^\[(?:mon|tue|wed|thu|fri|sat|sun) \d{2}/\d{2} \d{2}:\d{2}")

NOTIFICATION_PREFIXES: Tuple[str, ...] = (TASK_NOTIFICATION_MARKER, "<bash-notification>")
COMMAND_NAME_PREFIX: str = "<command-name>"
LOCAL_OUTPUT_PREFIX: str = "<local-command-stdout>"

_WRAPPED_WHOLE = re.compile(r'\A\n*<pasted_content id="([^"]*)">\n(.*)\n</pasted_content id="\1">\n?\Z', re.S)
_WRAPPED_AFTER_TYPING = re.compile(r'\n\n<pasted_content id="([^"]*)">\n(.*)\n</pasted_content id="\1">\n?\Z', re.S)

_COMMAND_NAME_RE = re.compile(r"<command-name>\s*([^<\s]+)\s*</command-name>")


def unwrap_pasted(text: str) -> Tuple[str, bool]:
    whole = _WRAPPED_WHOLE.match(text)
    if whole:
        return whole.group(2), True
    typed = _WRAPPED_AFTER_TYPING.search(text)
    if typed:
        return text[: typed.start()] + "\n\n" + typed.group(2), True
    return text, False


def message_blocks(record: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def text_of(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(b.get("text", "") for b in value if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def user_text(record: Mapping[str, Any]) -> str:
    message = record.get("message")
    return text_of(message.get("content") if isinstance(message, dict) else None)


def attachment_kinds(record: Mapping[str, Any]) -> List[str]:
    return [str(b["type"]) for b in message_blocks(record) if b.get("type") in ("image", "document")]


def origin_kind(record: Mapping[str, Any]) -> Optional[str]:
    origin = record.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    return kind if isinstance(kind, str) else None


def is_delivery_kind(kind: Optional[str]) -> bool:
    return kind is not None and kind not in (ORIGIN_KIND_HUMAN, ORIGIN_KIND_TASK_NOTICE)


def harness_origin(record: Mapping[str, Any]) -> Optional[str]:
    kind = origin_kind(record)
    if kind == ORIGIN_KIND_CHANNEL:
        return ORIGIN_CHANNEL
    if kind == ORIGIN_KIND_PEER:
        return ORIGIN_CROSSTALK
    if record.get("promptSource") == SYSTEM_PROMPT_SOURCE:
        return ORIGIN_SYSTEM
    if is_delivery_kind(kind):
        return ORIGIN_OTHER
    return None


def is_delivered(record: Mapping[str, Any]) -> bool:
    return is_delivery_kind(origin_kind(record))


def prompt_origin(record: Mapping[str, Any], text: str) -> str:
    recorded = harness_origin(record)
    if recorded:
        return recorded
    head = text.lstrip()
    if head.startswith("<channel"):
        return ORIGIN_CHANNEL
    if ENVELOPE_RE.search(text[:ENVELOPE_WINDOW]):
        return ORIGIN_CROSSTALK
    if OWNER_REF_RE.search(text):
        return ORIGIN_SWARM
    if MESSAGING_HEADER_RE.match(head):
        return ORIGIN_MESSAGING
    return ORIGIN_OTHER_TAG if head.startswith("<") else ORIGIN_HUMAN


def is_plain(record: Mapping[str, Any], text: str) -> bool:
    if record.get("isMeta") is True or harness_origin(record) in (ORIGIN_SYSTEM, ORIGIN_OTHER):
        return False
    return not text.lstrip().startswith("<")


def _version_tuple(record: Mapping[str, Any]) -> Optional[Tuple[int, ...]]:
    version = record.get("version")
    if not isinstance(version, str):
        return None
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None


def is_task_notice(record: Mapping[str, Any], text: str) -> bool:
    if "origin" in record:
        return is_task_notification(record)
    version = _version_tuple(record)
    if version is None or version >= ORIGIN_FIRST_VERSION:
        return False
    body = text.strip()
    return body.startswith(TASK_NOTIFICATION_MARKER) and body.endswith("</" + TASK_NOTIFICATION_MARKER[1:])


def command_name(text: str) -> Optional[str]:
    match = _COMMAND_NAME_RE.search(text)
    return match.group(1) if match else None


from __future__ import annotations

from typing import Any, Dict, List, Optional


TURN_END_SUBTYPE: str = "turn_duration"

TURN_END_DURATION: str = TURN_END_SUBTYPE
TURN_END_INTERRUPT: str = "interrupt"
TURN_END_NO_MODEL_TURN: str = "no_model_turn"

INTERRUPT_MARKERS: frozenset = frozenset(
    {"[Request interrupted by user]", "[Request interrupted by user for tool use]"}
)

LOCAL_COMMAND_PREFIXES: tuple = ("<command-name>", "<local-command-stdout>")

LOCAL_COMMAND_SUBTYPE: str = "local_command"

ENQUEUE_OPERATION: str = "enqueue"

TASK_NOTIFICATION_MARKER: str = "<task-notification>"

TASK_NOTIFICATION_KIND: str = "task-notification"

SYSTEM_PROMPT_SOURCE: str = "system"

# already running
QUEUED_COMMAND_ATTACHMENT: str = "queued_command"


def _record_text(record: Dict[str, Any]) -> str:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return ""


def _tag_value(text: str, tag: str) -> Optional[str]:
    opener = "<" + tag + ">"
    closer = "</" + tag + ">"
    start = text.find(opener)
    if start < 0:
        return None
    start += len(opener)
    end = text.find(closer, start)
    if end < 0:
        return None
    value = text[start:end].strip()
    return value or None


def _retired_ids(text: str) -> List[str]:
    if TASK_NOTIFICATION_MARKER not in text or _tag_value(text, "status") is None:
        return []
    return [
        value
        for value in (_tag_value(text, "tool-use-id"), _tag_value(text, "task-id"))
        if value
    ]


def _is_task_notification(record: Dict[str, Any]) -> bool:
    origin = record.get("origin")
    if not isinstance(origin, dict):
        return False
    return origin.get("kind") == TASK_NOTIFICATION_KIND


def _is_real_user_prompt(record: Dict[str, Any]) -> bool:
    if record.get("type") != "user":
        return False
    if record.get("isMeta") is True:
        return False
    if record.get("isSidechain") is True:
        return False
    if record.get("isCompactSummary") is True:
        return False
    if record.get("toolUseResult") is not None:
        return False
    if record.get("promptSource") == SYSTEM_PROMPT_SOURCE:
        return False
    return not _is_task_notification(record)


def _is_interrupt(record: Dict[str, Any]) -> bool:
    if record.get("type") != "user":
        return False
    if record.get("isMeta") is True or record.get("isSidechain") is True:
        return False
    if record.get("toolUseResult") is not None:
        return False
    return _record_text(record).strip() in INTERRUPT_MARKERS


def _is_local_command(record: Dict[str, Any]) -> bool:
    if record.get("type") == "system":
        return record.get("subtype") == LOCAL_COMMAND_SUBTYPE
    if record.get("type") != "user" or record.get("isSidechain") is True:
        return False
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, str) and content.lstrip().startswith(
        LOCAL_COMMAND_PREFIXES
    )


SYNTHETIC_MODEL: str = "<synthetic>"


def _is_resume_placeholder(record: Dict[str, Any]) -> bool:
    if record.get("type") != "assistant" or record.get("isSidechain") is True:
        return False
    if record.get("isApiErrorMessage") is True:
        return False
    message = record.get("message")
    if not isinstance(message, dict) or message.get("model") != SYNTHETIC_MODEL:
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return True
    return not any(
        isinstance(block, dict) and block.get("type") == "tool_use"
        for block in content
    )

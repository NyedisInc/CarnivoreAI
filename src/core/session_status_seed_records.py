
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence



TAIL_AT_REST: str = "at_rest"

TAIL_IN_FLIGHT: str = "in_flight"

TAIL_NO_MARKER: str = "no_marker"

TAIL_ABSENT: str = "absent"

# could not
# could not be read
TAIL_UNREADABLE: str = "unreadable"


REST_SYSTEM_SUBTYPES: frozenset[str] = frozenset(
    {"turn_duration", "stop_hook_summary"}
)

REST_STOP_REASONS: frozenset[str] = frozenset({"end_turn", "stop_sequence"})

IN_FLIGHT_STOP_REASONS: frozenset[str] = frozenset({"tool_use", "max_tokens"})

LOCAL_COMMAND_SUBTYPE: str = "local_command"

LOCAL_COMMAND_MARKERS: tuple[str, ...] = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
)


@dataclass(frozen=True)
class TranscriptRest:

    verdict: str
    at: Optional[datetime] = None
    detail: Optional[str] = None

    @property
    def at_rest(self) -> bool:
        return self.verdict == TAIL_AT_REST


def parse_timestamp(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_local_command_envelope(record: Any) -> bool:
    message = record.get("message") if isinstance(record, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    else:
        return False
    head = text.lstrip()[:200]
    return any(head.startswith(marker) for marker in LOCAL_COMMAND_MARKERS)


def classify_record(record: Any) -> Optional[bool]:
    if not isinstance(record, dict):
        return None
    if record.get("isSidechain") is True:
        return None

    kind = record.get("type")

    if kind == "system":
        subtype = record.get("subtype")
        if isinstance(subtype, str) and subtype in REST_SYSTEM_SUBTYPES:
            return True
        return None

    if kind == "assistant":
        message = record.get("message")
        reason = message.get("stop_reason") if isinstance(message, dict) else None
        if isinstance(reason, str):
            if reason in REST_STOP_REASONS:
                return True
            if reason in IN_FLIGHT_STOP_REASONS:
                return False
        return None

    if kind == "user":
        if is_local_command_envelope(record):
            return None
        return False

    return None


def classify_tail_records(records: Sequence[Any]) -> TranscriptRest:
    for record in reversed(list(records or ())):
        verdict = classify_record(record)
        if verdict is None:
            continue
        if verdict:
            return TranscriptRest(
                TAIL_AT_REST,
                at=parse_timestamp(record.get("timestamp")),
                detail=(
                    "the newest decidable record in the transcript tail "
                    "ends a turn and nothing follows it, so this "
                    "conversation is at rest"
                ),
            )
        return TranscriptRest(
            TAIL_IN_FLIGHT,
            detail=(
                "the newest decidable record in the transcript tail "
                "opens or continues a turn, so nothing is seeded - a "
                "file cannot carry the heartbeat a working claim needs"
            ),
        )
    return TranscriptRest(
        TAIL_NO_MARKER,
        detail=(
            "the transcript tail that was read holds no record this "
            "ladder can decide, which is not evidence that none exists "
            "further back than the bound"
        ),
    )

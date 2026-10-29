
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import structlog

from src.core.session_conversations import constants as K

logger = structlog.get_logger()

_COMMAND_RE = re.compile(r"<command-name>\s*(/[A-Za-z0-9_-]+)\s*</command-name>")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Head:

    command: Optional[str] = None
    forked_from: Optional[str] = None
    started_at: Optional[str] = None
    first_prompt: str = ""


def _records(path: Path, max_bytes: int, max_records: int) -> Iterator[Dict[str, Any]]:
    try:
        with path.open("rb") as handle:
            blob = handle.read(max_bytes)
    except OSError as exc:
        logger.debug("conversation_head_unreadable", path=str(path), error=str(exc))
        return
    seen = 0
    for raw in blob.split(b"\n"):
        if seen >= max_records:
            return
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if isinstance(record, dict):
            seen += 1
            yield record


def _text_of(record: Dict[str, Any]) -> str:
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def read_head(path: Path, *, max_bytes: int = K.HEAD_BYTES, max_records: int = K.HEAD_RECORDS) -> Head:
    command: Optional[str] = None
    forked_from: Optional[str] = None
    started_at: Optional[str] = None
    first_prompt = ""
    decided = False
    for record in _records(path, max_bytes, max_records):
        started_at = started_at or (record.get("timestamp") if isinstance(record.get("timestamp"), str) else None)
        pointer = record.get("forkedFrom")
        if forked_from is None and isinstance(pointer, dict) and isinstance(pointer.get("sessionId"), str):
            forked_from = pointer["sessionId"]
        if decided or record.get("type") != "user" or record.get("isMeta"):
            continue
        text = _text_of(record)
        if not text.strip():
            continue
        found = _COMMAND_RE.search(text)
        if found:
            command = command or found.group(1).lower()
            continue
        if text.lstrip().startswith("<local-command"):
            continue
        first_prompt = " ".join(_TAG_RE.sub(" ", text).split())[: K.FIRST_PROMPT_CHARS]
        decided = True
    return Head(command=command, forked_from=forked_from, started_at=started_at, first_prompt=first_prompt)


def ended_reason(head: Head, previous_id: Optional[str]) -> str:
    if head.command in K.CLEAR_COMMANDS:
        return K.CLEAR_COMMANDS[head.command]
    if head.forked_from:
        return K.ENDED_FORK
    return K.ENDED_SWITCH

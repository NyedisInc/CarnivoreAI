
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from src.core.message_model_secrets import scan_text
from src.core.skill_scout.text import one_line

logger = structlog.get_logger(__name__)

TAIL_BYTES = 2 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_SKILLS = 5
MAX_ERRORS = 3
MAX_CORRECTIONS = 3
CORRECTION_CHARS = 160
CORRECTION_LEADS = (
    "no,", "no.", "no ", "don't", "dont", "do not", "stop", "wrong",
    "that's wrong", "thats wrong", "that's not", "thats not", "actually",
    "instead", "undo", "revert", "not what i",
)


@dataclass(frozen=True)
class Digest:

    skills: List[str] = field(default_factory=list)
    tool_errors: List[str] = field(default_factory=list)
    corrections: List[str] = field(default_factory=list)


def is_clean(text: str) -> bool:
    return not scan_text(text, trust_vendor_marker=True)


def read_tail(path: str, limit: int = TAIL_BYTES) -> List[Dict[str, Any]]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            start = max(0, size - limit)
            handle.seek(start)
            data = handle.read(limit)
    except OSError as exc:
        logger.info("skill_scout_tail_unreadable", error=exc.__class__.__name__)
        return []
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]
    records: List[Dict[str, Any]] = []
    for raw in lines:
        if not raw or len(raw) > MAX_LINE_BYTES:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def user_text(record: Dict[str, Any]) -> Optional[str]:
    if record.get("type") != "user":
        return None
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if isinstance(p, str)) or None
    return None


def blocks_of(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def recurring_tool_errors(records: List[Dict[str, Any]]) -> List[str]:
    names: Dict[str, str] = {}
    errors: Counter = Counter()
    for record in records:
        for block in blocks_of(record):
            if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                names[block["id"]] = str(block.get("name") or "")
            elif block.get("type") == "tool_result" and block.get("is_error") is True:
                name = names.get(str(block.get("tool_use_id")), "")
                if name and is_clean(name):
                    errors[one_line(name, 40)] += 1
    return [f"{n} x{c}" for n, c in errors.most_common(MAX_ERRORS) if c >= 2]


def recent_corrections(records: List[Dict[str, Any]], marker: str) -> List[str]:
    found: List[str] = []
    for record in records:
        text = user_text(record)
        if not text or marker in text or not is_clean(text):
            continue
        line = one_line(text, CORRECTION_CHARS)
        if line.lower().startswith(CORRECTION_LEADS):
            found.append(line)
    return found[-MAX_CORRECTIONS:]


def top_skills(fired: List[str]) -> List[str]:
    clean = [n for n in fired if is_clean(n)]
    return [f"{one_line(n, 64)} x{c}" for n, c in Counter(clean).most_common(MAX_SKILLS)]


def build_digest(path: Optional[str], fired: List[str], marker: str) -> Digest:
    records = read_tail(path) if path else []
    return Digest(
        skills=[s for s in top_skills(fired) if is_clean(s)],
        tool_errors=[s for s in recurring_tool_errors(records) if is_clean(s)],
        corrections=[s for s in recent_corrections(records, marker) if is_clean(s)],
    )

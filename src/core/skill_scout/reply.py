
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

from src.core.skill_scout.digest import blocks_of, user_text
from src.core.skill_scout.prompt import MARKER, REPLY_PREFIX
from src.core.skill_scout.text import one_line

MAX_SUGGESTIONS = 10
REASON_CHARS = 200

STATE_NONE = "none"
STATE_WAITING = "waiting"
STATE_READY = "ready"

_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?" + re.escape(REPLY_PREFIX) + r"\s*(\S+?)\s*\|\s*(.+?)\s*$"
)


@dataclass(frozen=True)
class Suggestion:

    item_id: str
    reason: str


def parse_reply(texts: Iterable[str], known_ids: Set[str]) -> List[Suggestion]:
    found: List[Suggestion] = []
    seen: Set[str] = set()
    for text in texts:
        for line in text.splitlines():
            match = _LINE.match(line)
            if not match:
                continue
            item_id = match.group(1).strip("`'\"*")
            if item_id not in known_ids or item_id in seen:
                continue
            seen.add(item_id)
            found.append(Suggestion(item_id, one_line(match.group(2), REASON_CHARS)))
            if len(found) >= MAX_SUGGESTIONS:
                return found
    return found


_WRAPPED = ("<bash-", "<local-command-", "<command-")


def is_typed_prompt(record: Dict[str, Any], text: Optional[str]) -> bool:
    return (text is not None and not record.get("isMeta")
            and not text.lstrip().startswith(_WRAPPED))


def assistant_texts_after_request(records: List[Dict[str, Any]]) -> Optional[List[str]]:
    start: Optional[int] = None
    for index, record in enumerate(records):
        text = user_text(record)
        if is_typed_prompt(record, text) and text.lstrip().startswith(MARKER):
            start = index
    if start is None:
        return None
    texts: List[str] = []
    for record in records[start + 1:]:
        if is_typed_prompt(record, user_text(record)):
            break
        if record.get("type") != "assistant" or record.get("isSidechain"):
            continue
        for block in blocks_of(record):
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
    return texts


def read_reply(records: List[Dict[str, Any]], known_ids: Set[str]) -> tuple:
    texts = assistant_texts_after_request(records)
    if texts is None:
        return STATE_NONE, []
    found = parse_reply(texts, known_ids)
    return (STATE_READY if texts else STATE_WAITING), found

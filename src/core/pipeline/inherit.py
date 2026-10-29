
from __future__ import annotations

from typing import Iterable, Tuple

from src.core.pipeline import contract as C
from src.core.transcript_contract import RangeLine

COPY = "copy"
OWN = "own"
NEUTRAL = "neutral"


def classify(line: RangeLine, own_conversation_id: str) -> str:
    raw = line.parsed.raw
    if line.parsed.family != "claude" or not isinstance(raw, dict):
        return NEUTRAL
    if isinstance(raw.get("forkedFrom"), dict):
        return COPY
    session = raw.get("sessionId")
    if not isinstance(session, str) or not session:
        return NEUTRAL
    return OWN if session == own_conversation_id else COPY


def advance(state: str, inherited_start: int, inherited_end: int, lines: Iterable[RangeLine],
            own_conversation_id: str) -> Tuple[str, int, int]:
    for line in lines:
        if state == C.INHERIT_CLOSED:
            break
        kind = classify(line, own_conversation_id)
        if kind == COPY:
            if state == C.INHERIT_HEAD:
                inherited_start = line.offset
            state, inherited_end = C.INHERIT_OPEN, line.offset + line.length
        elif kind == OWN or state == C.INHERIT_OPEN:
            state = C.INHERIT_CLOSED
    return state, inherited_start, inherited_end

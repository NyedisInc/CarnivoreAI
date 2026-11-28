
from __future__ import annotations

import json

from src.core.transcript_contract.fields import json_type
from src.core.transcript_contract.parsed import (
    FAMILY_AGY,
    STATUS_BLANK,
    STATUS_NON_OBJECT,
    STATUS_OK,
    STATUS_UNPARSEABLE,
    ParsedLine,
    UnknownRecord,
)

KNOWN_AGY_TYPES = frozenset({
    "USER_INPUT",
    "PLANNER_RESPONSE",
    "GENERIC",
    "SYSTEM_MESSAGE",
    "CHECKPOINT",
    "ERROR_MESSAGE",
})


def parse_agy_line(text: str) -> ParsedLine:
    stripped = text.strip()
    if not stripped:
        return ParsedLine(FAMILY_AGY, STATUS_BLANK, text=text)
    try:
        obj = json.loads(stripped)
    except ValueError:
        return ParsedLine(FAMILY_AGY, STATUS_UNPARSEABLE, text=text)
    if not isinstance(obj, dict):
        return ParsedLine(FAMILY_AGY, STATUS_NON_OBJECT, f"<{json_type(obj)}>", text=text)
    kind = obj.get("type")
    kind_str = kind if isinstance(kind, str) else ""
    known = kind_str in KNOWN_AGY_TYPES
    return ParsedLine(FAMILY_AGY, STATUS_OK, kind_str, UnknownRecord(kind_str, obj), known, (), obj, text)

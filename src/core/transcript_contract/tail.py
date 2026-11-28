
from __future__ import annotations

import json
from typing import Any, Iterable, List, Mapping, Tuple

try:
    import orjson as _orjson
    _json_loads = _orjson.loads
except ImportError:
    _json_loads = json.loads

from src.core.transcript_contract.claude_parse import parse_claude_obj
from src.core.transcript_contract.parsed import ParsedLine

_NEWLINE = b"\n"


def decode_window(window: bytes, *, drop_first_line: bool = False) -> Tuple[dict, ...]:
    lines = window.split(_NEWLINE)
    if drop_first_line and lines:
        lines = lines[1:]
    objects: List[dict] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = _json_loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return tuple(objects)


def typed_lines(records: Iterable[Mapping[str, Any]]) -> Tuple[ParsedLine, ...]:
    return tuple(parse_claude_obj(record) for record in records)

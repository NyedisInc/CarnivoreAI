
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

from src.core.transcript_contract.claude_parse import parse_claude_line
from src.core.transcript_contract.codex_parse import parse_codex_line
from src.core.transcript_contract.parsed import (
    FAMILY_CLAUDE,
    FAMILY_CODEX,
    STATUS_UNPARSEABLE,
    ParsedLine,
)
from src.core.transcript_manifest.tail import line_serial

PARSERS: Dict[str, Callable[[str], ParsedLine]] = {
    FAMILY_CLAUDE: parse_claude_line,
    FAMILY_CODEX: parse_codex_line,
}


@dataclass(frozen=True)
class RangeLine:

    offset: int
    length: int
    parsed: ParsedLine
    raw: bytes = field(default=b"", repr=False, compare=False)


@dataclass(frozen=True)
class RangeParse:

    start: int
    lines: Tuple[RangeLine, ...]
    complete_end: int
    torn_bytes: int
    last_serial: Optional[str]


def parse_range(data: bytes, start: int, family: str) -> RangeParse:
    parse = PARSERS[family]
    lines = []
    pos = 0
    last_raw: Optional[bytes] = None
    while True:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        raw = data[pos:nl + 1]
        try:
            parsed = parse(raw.decode("utf-8"))
        except UnicodeDecodeError:
            parsed = ParsedLine(family, STATUS_UNPARSEABLE)
        lines.append(RangeLine(start + pos, len(raw), parsed, raw))
        last_raw = raw
        pos = nl + 1
    serial = line_serial(last_raw[:-1]) if last_raw is not None else None
    return RangeParse(start, tuple(lines), start + pos, len(data) - pos, serial)

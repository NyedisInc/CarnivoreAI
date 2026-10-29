
from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Set, Tuple

from src.core.deepsearch.extract import extract
from src.core.deepsearch.live.reader import RangeReader
from src.core.deepsearch.transcript_folders import folders_in_lines

Pending = List[Tuple[tuple, str]]


class RangeRows(NamedTuple):

    rows: Pending
    lines: int
    end_offset: int
    last_offset: int
    last_raw: bytes
    folders: Set[str]
    bytes_read: int = 0


def read_rows(source: Any, start: int, end: int, first_number: int, rules: Dict[str, Any], family: str,
              *, with_folders: bool = False) -> RangeRows:
    reader = RangeReader(source, start, end)
    rows: Pending = []
    last_offset, last_raw = start, b""
    folders: Set[str] = set()
    for number, (offset, line) in enumerate(reader, start=first_number):
        last_offset, last_raw = offset, line
        if with_folders:
            folders |= folders_in_lines((line,))
        found = extract(line, rules, family)
        if found is not None:
            rows.append(((0, offset, len(line), number, number, found[0]), found[1]))
    return RangeRows(rows, reader.lines, reader.end_offset, last_offset, last_raw, folders, reader.bytes_read)

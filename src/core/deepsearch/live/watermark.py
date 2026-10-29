
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from src.core.deepsearch import constants as K


@dataclass(frozen=True)
class Start:

    mode: str
    offset: int
    lines: int
    reason: Optional[str] = None
    checked_bytes: int = 0


def line_holds(source, serial_offset: Optional[int], end: int, serial: Optional[str]) -> Tuple[bool, int]:
    from src.core.transcript_manifest.tail import line_serial

    if serial is None or serial_offset is None or not 0 <= serial_offset < end:
        return False, 0
    if isinstance(source, (str, Path)):
        with open(source, "rb") as handle:
            handle.seek(serial_offset)
            line = handle.read(end - serial_offset)
    else:
        line = source.read(serial_offset, end - serial_offset)
    holds = len(line) == end - serial_offset and line.endswith(b"\n") and line_serial(line[:-1]) == serial
    return holds, len(line)


FULL_START = Start(K.MODE_FULL, 0, 0, K.FULL_FIRST)


def verify(path: Path, size: int, offset: int, lines: int, serial: Optional[str],
           serial_offset: Optional[int]) -> Start:
    if offset > size:
        return Start(K.MODE_FULL, 0, 0, K.FULL_BEYOND_SIZE)
    if offset == 0:
        return Start(K.MODE_APPEND, 0, 0)
    holds, read = line_holds(path, serial_offset, offset, serial)
    if not holds:
        return Start(K.MODE_FULL, 0, 0, K.FULL_HEAD_CHANGED, read)
    return Start(K.MODE_APPEND, offset, lines, None, read)

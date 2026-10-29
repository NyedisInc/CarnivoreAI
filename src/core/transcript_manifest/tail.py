
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.transcript_manifest import constants as K


@dataclass(frozen=True)
class LastLine:

    serial: Optional[str]
    offset: Optional[int]
    end: Optional[int]


NO_LINE = LastLine(None, None, None)


def line_serial(line: bytes) -> str:
    try:
        record = json.loads(line)
    except ValueError:
        record = None
    if isinstance(record, dict):
        uuid = record.get("uuid")
        if isinstance(uuid, str) and uuid:
            return uuid
    return K.SERIAL_HASH_PREFIX + hashlib.sha256(line).hexdigest()[:K.SERIAL_HASH_CHARS]


def read_last_line(path: Path, size: int, *, max_bytes: int = K.TAIL_MAX_BYTES) -> LastLine:
    if size <= 0:
        return NO_LINE
    window = min(K.TAIL_WINDOW_BYTES, size)
    with open(path, "rb") as handle:
        while True:
            start = size - window
            handle.seek(start)
            buf = handle.read(window)
            end_nl = buf.rfind(b"\n")
            if end_nl < 0:
                if start == 0 or window >= max_bytes:
                    return NO_LINE
            else:
                begin = buf.rfind(b"\n", 0, end_nl)
                if begin >= 0 or start == 0:
                    line_start = begin + 1 if begin >= 0 else 0
                    line = buf[line_start:end_nl]
                    return LastLine(line_serial(line), start + line_start, start + end_nl + 1)
                if window >= max_bytes:
                    return NO_LINE
            window = min(window * 2, size, max_bytes)


def serial_at(path: Path, offset: int, *, max_bytes: int = K.TAIL_MAX_BYTES) -> Optional[str]:
    if offset < 0:
        return None
    with open(path, "rb") as handle:
        if offset > os.fstat(handle.fileno()).st_size:
            return None
        handle.seek(offset)
        chunk = b""
        while len(chunk) < max_bytes:
            more = handle.read(K.TAIL_WINDOW_BYTES)
            if not more:
                return None
            newline = more.find(b"\n")
            if newline >= 0:
                return line_serial(chunk + more[:newline])
            chunk += more
    return None

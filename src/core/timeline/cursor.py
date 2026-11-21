
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Tuple

from src.core.pipeline import contract as C
from src.core.pipeline import reader as pipeline_reader
from src.core.timeline.model import is_ident

MAX_BACK_SCAN_BYTES: int = 64 * 1024 * 1024
BACK_SCAN_CHUNK: int = 64 * 1024
CURSOR_FIELDS: int = 4
NEWLINE = b"\n"
MEMO_LINE_BYTES: int = 5 * 1024 * 1024
EDGE_BYTES: int = 4096
MAX_CHECKED: int = 64


class CursorError(ValueError):
    pass


@dataclass(frozen=True)
class Cursor:

    conv: str
    file_key: str
    offset: int
    serial: str

    def wire(self) -> str:
        return f"{self.conv}:{self.file_key}:{self.offset}:{self.serial}"


def parse(text: str) -> Cursor:
    parts = text.split(":", CURSOR_FIELDS - 1)
    if len(parts) != CURSOR_FIELDS:
        raise CursorError("a cursor is <conv>:<file_key>:<offset>:<serial>")
    conv, file_key, offset_text, serial = parts
    if not (is_ident(conv) and is_ident(file_key)) or not offset_text.isdigit():
        raise CursorError("a cursor names a conversation, a file key and a byte offset")
    offset = int(offset_text)
    if offset == 0 and serial:
        raise CursorError("a cursor at offset 0 has no serial")
    if offset > 0 and not serial:
        raise CursorError("a cursor past offset 0 needs the serial of the line it ends")
    return Cursor(conv, file_key, offset, serial)


def line_start_before(path: str, offset: int) -> Optional[int]:
    if offset <= 0:
        return None
    with open(path, "rb") as handle:
        handle.seek(offset - 1)
        if handle.read(1) != NEWLINE:
            return None
        high, scanned = offset - 1, 0
        while high > 0 and scanned < MAX_BACK_SCAN_BYTES:
            low = max(0, high - BACK_SCAN_CHUNK)
            handle.seek(low)
            chunk = handle.read(high - low)
            found = chunk.rfind(NEWLINE)
            if found >= 0:
                return low + found + 1
            high, scanned = low, scanned + len(chunk)
        return 0 if high == 0 else None


_CheckKey = Tuple[str, int, int, str]
_checked: "OrderedDict[_CheckKey, Tuple[int, bytes]]" = OrderedDict()
_checked_lock = threading.Lock()


def _edges(path: str, start: int, end: int) -> bytes:
    with open(path, "rb") as handle:
        handle.seek(start)
        head = handle.read(min(EDGE_BYTES, end - start))
        handle.seek(max(start, end - EDGE_BYTES))
        return head + handle.read(min(EDGE_BYTES, end - start))


def _remembered(path: str, key: _CheckKey, offset: int) -> bool:
    with _checked_lock:
        held = _checked.get(key)
        if held is not None:
            _checked.move_to_end(key)
    return held is not None and _edges(path, held[0], offset) == held[1]


def _remember(path: str, key: _CheckKey, start: int, offset: int) -> None:
    if offset - start <= MEMO_LINE_BYTES:
        return
    fingerprint = _edges(path, start, offset)
    with _checked_lock:
        _checked[key] = (start, fingerprint)
        _checked.move_to_end(key)
        while len(_checked) > MAX_CHECKED:
            _checked.popitem(last=False)


def forget_checked() -> None:
    with _checked_lock:
        _checked.clear()


def check(path: str, cursor: Cursor, *, size: Optional[int] = None) -> Optional[str]:
    if cursor.offset == 0:
        return None
    size = os.stat(path).st_size if size is None else size
    if cursor.offset > size:
        return C.EV_TRUNCATED
    key = (path, os.stat(path).st_ino, cursor.offset, cursor.serial)
    if _remembered(path, key, cursor.offset):
        return None
    start = line_start_before(path, cursor.offset)
    if start is None:
        return C.EV_FILE_REWRITTEN
    reset = pipeline_reader.check_cursor(path, size, cursor.offset, cursor.serial, start).reset
    if reset is None:
        _remember(path, key, start, cursor.offset)
    return reset

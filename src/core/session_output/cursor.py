
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CURSOR_TAG = "c1"
MAX_READ_BYTES = 64 * 1024


class CursorError(ValueError):
    pass


@dataclass(frozen=True)
class Cursor:

    inode: int
    stamp_ms: int
    offset: int

    def encode(self) -> str:
        return f"{CURSOR_TAG}.{self.inode}.{self.stamp_ms}.{self.offset}"


@dataclass(frozen=True)
class ReadResult:

    reset: bool
    data: bytes
    next: Cursor
    more: bool


def parse(text: object) -> Cursor:
    if not isinstance(text, str) or len(text) > 80:
        raise CursorError("since must be a cursor string from an earlier answer")
    parts = text.split(".")
    if len(parts) != 4 or parts[0] != CURSOR_TAG or not all(p.isdigit() for p in parts[1:]):
        raise CursorError("since must be a cursor string from an earlier answer")
    return Cursor(int(parts[1]), int(parts[2]), int(parts[3]))


def stamp_ms(stamp: float) -> int:
    return int(stamp * 1000)


def at_end(path: Path, stamp: float) -> Cursor:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return Cursor(0, stamp_ms(stamp), 0)
    return Cursor(st.st_ino, stamp_ms(stamp), st.st_size)


def read_since(path: Path, stamp: float, cursor: Cursor, limit: int = MAX_READ_BYTES) -> ReadResult:
    now_ms = stamp_ms(stamp)
    try:
        fd = os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        return ReadResult(False, b"", cursor, False)
    try:
        st = os.fstat(fd)
        if st.st_ino != cursor.inode or now_ms != cursor.stamp_ms or st.st_size < cursor.offset:
            return ReadResult(True, b"", Cursor(st.st_ino, now_ms, 0), st.st_size > 0)
        want = min(limit, st.st_size - cursor.offset)
        if want <= 0:
            return ReadResult(False, b"", cursor, False)
        data = os.pread(fd, want, cursor.offset)
    finally:
        os.close(fd)
    end = cursor.offset + len(data)
    return ReadResult(False, data, Cursor(cursor.inode, cursor.stamp_ms, end), st.st_size > end)


def read_tail(path: Path, stamp: float, cursor: Cursor, limit: int = MAX_READ_BYTES) -> ReadResult:
    try:
        size = os.stat(path).st_size
    except FileNotFoundError:
        return ReadResult(False, b"", cursor, False)
    start = max(cursor.offset, size - limit)
    if start == cursor.offset:
        return read_since(path, stamp, cursor, limit)
    return read_since(path, stamp, Cursor(cursor.inode, cursor.stamp_ms, start), limit)

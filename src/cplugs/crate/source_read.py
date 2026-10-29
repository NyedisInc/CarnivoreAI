
from __future__ import annotations

import hashlib
import io
import os
import sys
from typing import Any, Callable, Iterable, Iterator, Optional

from src.cplugs.sdk import blob_codec as bc
from src.cplugs.sdk import crate_format as cf


class SourceUnstable(Exception):

    def __init__(self, path: str, detail: str = "changed while it was read") -> None:
        super().__init__(f"{path} {detail}")
        self.path, self.detail = path, detail


def _sliced(chunks: Iterable[bytes]) -> Iterator[bytes]:
    cap, step = cf.constants.MAX_CHUNK_LENGTH, bc.BINARY_CHUNK_BYTES
    for chunk in chunks:
        if len(chunk) <= cap:
            yield chunk
            continue
        for start in range(0, len(chunk), step):
            yield chunk[start:start + step]


def disk_chunks(fd: int, st: os.stat_result, line_mode: bool, path: str = "") -> Iterator[bytes]:
    stream = io.FileIO(fd, "rb", closefd=False)
    reader = bc.ChunkReader(stream, st.st_size, line_mode, keep_tail=True)
    yield from _sliced(reader)
    if reader.short or reader.read_bytes != st.st_size or reader.length != st.st_size:
        raise SourceUnstable(path or f"fd {fd}", "ended before the size it had when it was opened")


def stream_chunks(parts: Iterable[bytes], length: int, line_mode: bool) -> Iterator[bytes]:
    reader = bc.ChunkReader(io.BufferedReader(bc.IterStream(parts)), length, line_mode, keep_tail=True)
    yield from _sliced(reader)
    if reader.short or reader.length != length:
        raise SourceUnstable("stream", f"held {reader.length} of {length} bytes")


def open_chunks(parts: Iterable[bytes], line_mode: bool) -> Iterator[bytes]:
    reader = bc.ChunkReader(io.BufferedReader(bc.IterStream(parts)), sys.maxsize, line_mode, keep_tail=True)
    yield from _sliced(reader)


def vault_chunks(reader: Any, line_mode: bool, pace: Optional[Callable[[], None]] = None) -> Iterator[bytes]:
    def slices() -> Iterator[bytes]:
        offset, total = 0, int(reader.length)
        while offset < total:
            block = reader.read(offset, min(bc.READ_BYTES, total - offset))
            if not block:
                return
            offset += len(block)
            if pace is not None:
                pace()
            yield block

    yield from stream_chunks(slices(), int(reader.length), line_mode)


def stat_unchanged(before: os.stat_result, after: os.stat_result) -> bool:
    return (before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns)


def rehash(path: str) -> str:
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with io.FileIO(fd, "rb") as handle:
        for block in iter(lambda: handle.read(bc.READ_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()

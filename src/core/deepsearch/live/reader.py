
from __future__ import annotations

from pathlib import Path
from typing import Iterator, Tuple, Union

from src.core.deepsearch import constants as K


class RangeReader:

    def __init__(self, source, start: int, end: int, *, chunk: int = K.LIVE_READ_CHUNK) -> None:
        is_path = isinstance(source, (str, Path))
        self.path = Path(source) if is_path else None
        self._source = None if is_path else source
        self.start, self.end, self.chunk = int(start), int(end), int(chunk)
        self.bytes_read = 0
        self.end_offset = self.start
        self.lines = 0

    def __iter__(self) -> Iterator[Tuple[int, bytes]]:
        if self.end <= self.start:
            return
        if self._source is not None:
            for offset, line in self._source.lines(self.start, self.end):
                self.bytes_read += len(line)
                self.lines += 1
                self.end_offset = offset + len(line)
                yield offset, line
            return
        pending = b""
        pending_at = self.start
        with open(self.path, "rb") as handle:
            handle.seek(self.start)
            left = self.end - self.start
            while left > 0:
                block = handle.read(min(self.chunk, left))
                if not block:
                    break
                self.bytes_read += len(block)
                left -= len(block)
                pending += block
                cut = 0
                while True:
                    newline = pending.find(b"\n", cut)
                    if newline < 0:
                        break
                    line = pending[cut:newline + 1]
                    yield pending_at + cut, line
                    self.lines += 1
                    self.end_offset = pending_at + newline + 1
                    cut = newline + 1
                pending, pending_at = pending[cut:], pending_at + cut


def read_line(source: Union[str, Path, object], offset: int, length: int) -> bytes:
    if not isinstance(source, (str, Path)):
        return source.read(offset, length)
    with open(source, "rb") as handle:
        handle.seek(offset)
        return handle.read(length)

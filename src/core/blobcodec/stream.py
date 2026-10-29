
from __future__ import annotations

import io
from typing import Any, Iterable, Iterator


class IterStream(io.RawIOBase):

    def __init__(self, parts: Iterable[bytes]) -> None:
        super().__init__()
        self._parts: Iterator[bytes] = iter(parts)
        self._pending = b""

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        view = memoryview(b).cast("B")
        while not self._pending:
            nxt = next(self._parts, None)
            if nxt is None:
                return 0
            self._pending = bytes(nxt)
        piece = self._pending[:len(view)]
        self._pending = self._pending[len(piece):]
        view[:len(piece)] = piece
        return len(piece)

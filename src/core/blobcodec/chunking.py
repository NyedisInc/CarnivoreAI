
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import BinaryIO, Iterator, List, Optional

CHUNK_TARGET_BYTES: int = 1024 * 1024
BINARY_CHUNK_BYTES: int = 1024 * 1024
READ_BYTES: int = 1024 * 1024


@dataclass(frozen=True)
class ChunkRef:

    sha256: str
    length: int


def chain_sha(refs: List[ChunkRef]) -> str:
    digest = hashlib.sha256()
    for ref in refs:
        digest.update(f"{ref.sha256}:{ref.length}\n".encode("ascii"))
    return digest.hexdigest()


def refs_to_json(refs: List[ChunkRef]) -> List[List]:
    return [[r.sha256, r.length] for r in refs]


def refs_from_json(rows: List[List]) -> List[ChunkRef]:
    try:
        return [ChunkRef(str(sha), int(length)) for sha, length in rows]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"malformed chunk list: {exc}") from exc


class ChunkReader:
    """Iterate the chunks of one open file, reading at most ``limit`` bytes.

    Inputs: stream (binary, positioned at 0); limit (bytes to read at most, the size seen by stat before the read);
      line_mode (JSONL: cut at line boundaries and drop a torn last line); target (line chunk size); keep_tail (line mode:
      keep a last line without a newline as a final chunk instead of dropping it; for a file that will not grow, such as one
      read back from the old tree).
    Attributes after iteration: ``read_bytes`` (bytes taken from the file), ``length`` (bytes in the chunks), ``torn_bytes``
      (a last line without a newline, left out), ``lines`` (newlines counted in line mode, else 0), ``short`` (the stream
      ended before ``limit`` bytes: the file shrank or a read came back empty, so what was read is not the whole file).
    Example: r = ChunkReader(open(p, 'rb'), size, True); parts = list(r)
    """

    def __init__(self, stream: BinaryIO, limit: int, line_mode: bool, target: Optional[int] = None,
                 keep_tail: bool = False) -> None:
        self._stream, self._limit, self._line, self._keep_tail = stream, limit, line_mode, keep_tail
        self._target = max(1, target or (CHUNK_TARGET_BYTES if line_mode else BINARY_CHUNK_BYTES))
        self.read_bytes = self.length = self.torn_bytes = self.lines = 0
        self.short = False

    def _fill(self, buf: bytearray) -> bool:
        room = self._limit - self.read_bytes
        if room <= 0:
            return False
        block = self._stream.read(min(READ_BYTES, room))
        if not block:
            self.short = True
            return False
        self.read_bytes += len(block)
        buf += block
        return True

    def __iter__(self) -> Iterator[bytes]:
        buf = bytearray()
        more = True
        while True:
            if self._line:
                cut = self._line_cut(buf)
                while cut < 0 and more:
                    more = self._fill(buf)
                    cut = self._line_cut(buf)
                if cut < 0:
                    cut = len(buf) if self._keep_tail else buf.rfind(b"\n") + 1
                    if cut <= 0:
                        self.torn_bytes = len(buf)
                        return
            else:
                while len(buf) < self._target and more:
                    more = self._fill(buf)
                cut = min(len(buf), self._target)
                if cut == 0:
                    return
            chunk = bytes(buf[:cut])
            del buf[:cut]
            self.length += len(chunk)
            self.lines += chunk.count(b"\n") if self._line else 0
            yield chunk
            if self._line and not more and not buf:
                return

    def _line_cut(self, buf: bytearray) -> int:
        if len(buf) < self._target:
            return -1
        found = buf.find(b"\n", self._target - 1)
        return found + 1 if found >= 0 else -1

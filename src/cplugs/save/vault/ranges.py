
from __future__ import annotations

import bisect
import threading
from collections import OrderedDict
from itertools import accumulate
from typing import Iterator, List, Optional, Tuple

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.manifest import FileEntry
from src.cplugs.sdk.blob_codec import BlobCorrupt, BlobMissing, ChunkRef
from src.core.deepsearch.fallback_hook import FallbackUnavailable


class ChunkCache:

    def __init__(self, capacity: int = K.RANGE_CACHE_CHUNKS) -> None:
        self._capacity = max(1, int(capacity))
        self._items: "OrderedDict[str, bytes]" = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def get(self, blobs: BlobStore, ref: ChunkRef) -> bytes:
        with self._lock:
            hit = self._items.get(ref.sha256)
            if hit is not None:
                self._items.move_to_end(ref.sha256)
                return hit
        try:
            raw = blobs.get(ref)
        except (BlobMissing, BlobCorrupt, ValueError) as exc:
            raise FallbackUnavailable(f"chunk {ref.sha256[:12]}: {exc}") from exc
        with self._lock:
            self._items[ref.sha256] = raw
            self._items.move_to_end(ref.sha256)
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)
        return raw


class EntryReader:

    def __init__(self, blobs: BlobStore, entry: FileEntry, cache: Optional[ChunkCache] = None) -> None:
        self._blobs, self._chunks = blobs, list(entry.chunks)
        self._cache = cache if cache is not None else ChunkCache()
        ends: List[int] = list(accumulate(c.length for c in self._chunks))
        self._starts = [0] + ends[:-1]
        self._ends = ends
        self.length = ends[-1] if ends else 0

    def _span(self, start: int, end: int) -> Iterator[Tuple[int, bytes]]:
        end = min(end, self.length)
        if start < 0 or start >= end:
            return
        index = bisect.bisect_right(self._ends, start)
        while index < len(self._chunks) and self._starts[index] < end:
            raw = self._cache.get(self._blobs, self._chunks[index])
            low = max(start, self._starts[index]) - self._starts[index]
            high = min(end, self._ends[index]) - self._starts[index]
            yield self._starts[index] + low, raw[low:high]
            index += 1

    def read(self, offset: int, length: int) -> bytes:
        return b"".join(piece for _, piece in self._span(int(offset), int(offset) + max(0, int(length))))

    def lines(self, start: int, end: int) -> Iterator[Tuple[int, bytes]]:
        pending, pending_at = b"", int(start)
        for _, piece in self._span(int(start), int(end)):
            pending += piece
            cut = 0
            while True:
                newline = pending.find(b"\n", cut)
                if newline < 0:
                    break
                yield pending_at + cut, pending[cut:newline + 1]
                cut = newline + 1
            pending, pending_at = pending[cut:], pending_at + cut

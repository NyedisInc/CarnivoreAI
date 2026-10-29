
from __future__ import annotations

import gzip
import threading
from dataclasses import dataclass
from typing import Callable, Optional

GZIP_LEVEL = 6


@dataclass(frozen=True)
class _Entry:

    mtime: float
    size: int
    gzip_bytes: bytes


_cache: dict[str, _Entry] = {}
_lock = threading.Lock()


def peek(cache_key: str, mtime: float, size: int) -> Optional[bytes]:
    with _lock:
        entry = _cache.get(cache_key)
    if entry is not None and entry.mtime == mtime and entry.size == size:
        return entry.gzip_bytes
    return None


def compress_and_cache(
    cache_key: str, mtime: float, size: int, get_raw_bytes: Callable[[], bytes]
) -> bytes:
    raw = get_raw_bytes()
    compressed = gzip.compress(raw, compresslevel=GZIP_LEVEL)
    with _lock:
        _cache[cache_key] = _Entry(mtime=mtime, size=size, gzip_bytes=compressed)
    return compressed


def gzip_cached(
    cache_key: str, mtime: float, size: int, get_raw_bytes: Callable[[], bytes]
) -> bytes:
    cached = peek(cache_key, mtime, size)
    if cached is not None:
        return cached
    return compress_and_cache(cache_key, mtime, size, get_raw_bytes)


def warm(entries: list[tuple[str, float, int, Callable[[], bytes]]]) -> int:
    count = 0
    for cache_key, mtime, size, get_raw_bytes in entries:
        gzip_cached(cache_key, mtime, size, get_raw_bytes)
        count += 1
    return count


def cache_size() -> int:
    with _lock:
        return len(_cache)

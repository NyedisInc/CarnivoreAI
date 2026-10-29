
from __future__ import annotations

import gzip
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
import importlib

from src.core import static_cache


def _fresh_module():
    return importlib.reload(static_cache)


def test_peek_misses_on_an_entry_never_compressed() -> None:
    sc = _fresh_module()
    assert sc.peek("nothing-here", 1.0, 10) is None


def test_compress_and_cache_then_peek_hits() -> None:
    sc = _fresh_module()
    raw = b"hello world" * 100
    compressed = sc.compress_and_cache("key-a", 1000.0, len(raw), lambda: raw)
    assert gzip.decompress(compressed) == raw

    hit = sc.peek("key-a", 1000.0, len(raw))
    assert hit == compressed


def test_peek_misses_when_mtime_changed() -> None:
    sc = _fresh_module()
    raw = b"version one"
    sc.compress_and_cache("key-b", 1000.0, len(raw), lambda: raw)
    assert sc.peek("key-b", 2000.0, len(raw)) is None


def test_peek_misses_when_size_changed() -> None:
    sc = _fresh_module()
    raw = b"short"
    sc.compress_and_cache("key-c", 1000.0, len(raw), lambda: raw)
    assert sc.peek("key-c", 1000.0, len(raw) + 1) is None


def test_a_changed_file_recompresses_to_the_new_content() -> None:
    sc = _fresh_module()
    old = b"the old content"
    new = b"the NEW content, deployed"

    first = sc.gzip_cached("key-d", 1.0, len(old), lambda: old)
    assert gzip.decompress(first) == old

    assert gzip.decompress(sc.gzip_cached("key-d", 1.0, len(old), lambda: old)) == old

    second = sc.gzip_cached("key-d", 2.0, len(new), lambda: new)
    assert gzip.decompress(second) == new


def test_get_raw_bytes_is_never_called_on_a_hit() -> None:
    sc = _fresh_module()
    raw = b"cached content"
    sc.compress_and_cache("key-e", 1.0, len(raw), lambda: raw)

    def _boom():
        raise AssertionError("get_raw_bytes must not be called on a cache hit")

    result = sc.gzip_cached("key-e", 1.0, len(raw), _boom)
    assert gzip.decompress(result) == raw


def test_warm_populates_every_entry_up_front() -> None:
    sc = _fresh_module()
    entries = [
        ("k1", 1.0, 3, lambda: b"abc"),
        ("k2", 1.0, 3, lambda: b"xyz"),
    ]
    count = sc.warm(entries)
    assert count == 2
    assert sc.peek("k1", 1.0, 3) is not None
    assert sc.peek("k2", 1.0, 3) is not None
    assert gzip.decompress(sc.peek("k1", 1.0, 3)) == b"abc"
    assert gzip.decompress(sc.peek("k2", 1.0, 3)) == b"xyz"


def test_cache_size_reflects_distinct_keys() -> None:
    sc = _fresh_module()
    assert sc.cache_size() == 0
    sc.compress_and_cache("only-key", 1.0, 1, lambda: b"a")
    assert sc.cache_size() == 1
    sc.compress_and_cache("only-key", 2.0, 1, lambda: b"b")
    assert sc.cache_size() == 1

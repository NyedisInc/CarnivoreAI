
from __future__ import annotations

import pytest

from src.core.blobcodec import chunking
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.ranges import ChunkCache, EntryReader
from src.core.deepsearch.fallback_hook import FallbackUnavailable
from tests.python.cplugs.save.vault_helpers import CONV, World, jsonl


@pytest.fixture(autouse=True)
def tiny_chunks(monkeypatch):
    monkeypatch.setattr(chunking, "CHUNK_TARGET_BYTES", 2048)


@pytest.fixture
def stored(tmp_path):
    world = World(tmp_path)
    body = jsonl(40)
    world.write_conversation(body)
    world.capture()
    entry = world.vault.manifests.newest(CONV).main()
    assert len(entry.chunks) > 3
    return world, body, entry


def _line_starts(body: bytes):
    out, at = [], 0
    for line in body.splitlines(keepends=True):
        out.append((at, line))
        at += len(line)
    return out


def test_every_line_is_read_at_its_original_offset_across_chunk_edges(stored):
    world, body, entry = stored
    reader = EntryReader(world.vault.blobs, entry)
    assert reader.length == len(body)
    for offset, line in _line_starts(body):
        assert reader.read(offset, len(line)) == line
    assert list(reader.lines(0, len(body))) == _line_starts(body)


def test_a_span_that_crosses_edges_joins_them_and_a_read_past_the_end_is_short(stored):
    world, body, entry = stored
    reader = EntryReader(world.vault.blobs, entry)
    assert reader.read(1000, 3000) == body[1000:4000]
    assert reader.read(len(body) - 10, 500) == body[-10:]
    assert reader.read(len(body) + 5, 10) == b""


def test_lines_leaves_a_partial_last_line_and_starts_at_a_line_start(stored):
    world, body, entry = stored
    reader = EntryReader(world.vault.blobs, entry)
    starts = _line_starts(body)
    cut = starts[10][0] + 40
    assert list(reader.lines(starts[3][0], cut)) == starts[3:10]


def test_the_cache_is_bounded_and_a_repeat_read_does_not_touch_the_blob_store(stored, monkeypatch):
    world, body, entry = stored
    cache = ChunkCache(2)
    reader = EntryReader(world.vault.blobs, entry, cache)
    list(reader.lines(0, len(body)))
    assert len(cache) == 2
    calls = []
    real = BlobStore.get
    monkeypatch.setattr(BlobStore, "get", lambda self, ref: (calls.append(ref.sha256), real(self, ref))[1])
    reader.read(len(body) - 50, 50)
    reader.read(len(body) - 50, 50)
    assert calls == []
    reader.read(0, 10)
    assert len(calls) == 1


def test_a_missing_or_damaged_chunk_is_unavailable_never_wrong_bytes(stored):
    world, body, entry = stored
    first, second = entry.chunks[0], entry.chunks[1]
    path, _codec = world.vault.blobs.find(second.sha256)
    path.write_bytes(b"garbage")
    reader = EntryReader(world.vault.blobs, entry)
    assert reader.read(0, 100) == body[:100]
    with pytest.raises(FallbackUnavailable):
        reader.read(first.length + 1, 10)
    path.unlink()
    with pytest.raises(FallbackUnavailable):
        EntryReader(world.vault.blobs, entry).read(first.length + 1, 10)

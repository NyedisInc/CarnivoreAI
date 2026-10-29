
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.core.blobcodec import chunking
from src.core.blobcodec.codec import _zstd as zstd_module
from src.cplugs.save.vault import restore
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.ingest import DatalessSource, SourceUnstable, ingest_file
from src.cplugs.sdk.blob_codec import BlobCorrupt, ChunkReader, ChunkRef, chain_sha
from tests.python.cplugs.save.vault_helpers import CONV, ENC, World, jsonl


def _chunks_of(world: World) -> list:
    manifest = world.vault.manifests.newest(CONV)
    return [c.sha256 for c in manifest.main().chunks]


def test_an_append_adds_only_the_new_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(chunking, "CHUNK_TARGET_BYTES", 64 * 1024)
    world = World(tmp_path)
    main = world.write_conversation(jsonl(2000))
    first = world.capture()
    assert first.status == "written"
    before = _chunks_of(world)
    assert len(before) >= 6
    first_bytes = world.vault.blobs.new_bytes
    world.vault.blobs.new_blobs = world.vault.blobs.new_bytes = 0

    with open(main, "ab") as handle:
        handle.write(jsonl(30, seed=9))
    second = world.capture(reason="follow")
    assert second.status == "written"
    after = _chunks_of(world)
    assert after[: len(before) - 1] == before[:-1]
    assert second.new_chunks <= 2 and world.vault.blobs.new_bytes < 0.1 * first_bytes


def test_restore_is_byte_identical_for_every_file(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(3000), subagents=3, tool_results=2)
    world.capture()
    manifest = world.vault.manifests.newest(CONV)
    assert {f.role for f in manifest.files} == {"transcript", "subagent", "conversation_file", "tool_result", "file_history"}
    out = tmp_path / "restored"
    result = restore.restore_to_root(world.vault.blobs, manifest, out)
    assert len(result.written) == len(manifest.files) >= 9
    for entry in manifest.files:
        original = Path(entry.source_path).read_bytes()
        copy = (out / entry.home / entry.rel).read_bytes()
        assert copy == original and chain_sha(entry.chunks) == entry.sha256 and entry.sha_kind == "chain"
        assert hashlib.sha256(copy).hexdigest() != entry.sha256


def test_restore_refuses_a_differing_file_and_writes_nothing(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(50))
    world.capture()
    manifest = world.vault.manifests.newest(CONV)
    out = tmp_path / "restored"
    target = out / "claude" / manifest.main().rel
    target.parent.mkdir(parents=True)
    target.write_bytes(b"someone else's file\n")
    with pytest.raises(restore.RestoreConflict):
        restore.restore_to_root(world.vault.blobs, manifest, out)
    assert target.read_bytes() == b"someone else's file\n"
    assert [p for p in out.rglob("*") if p.is_file()] == [target]
    again = restore.restore_to_root(world.vault.blobs, manifest, out, skip_conflicts=True)
    assert again.skipped_conflicts == [target] and len(again.written) == len(manifest.files) - 1


def test_a_damaged_chunk_is_an_error_not_a_wrong_file(tmp_path):
    world = World(tmp_path)
    world.write_conversation(jsonl(50))
    world.capture()
    manifest = world.vault.manifests.newest(CONV)
    sha = manifest.main().chunks[0].sha256
    path, _codec = world.vault.blobs.find(sha)
    blob = BlobStore(world.vault.root, codec=_codec)
    path.write_bytes(zstd_module.compress(b"not the chunk") if _codec == "zstd"
                     else __import__("lzma").compress(b"not the chunk"))
    with pytest.raises(BlobCorrupt):
        blob.get(ChunkRef(sha, manifest.main().chunks[0].length))
    with pytest.raises(restore.RestoreError):
        restore.verify_manifest(world.vault.blobs, manifest)


def test_a_line_still_being_written_is_not_stored_torn(tmp_path):
    world = World(tmp_path)
    body = jsonl(40) + b'{"type":"assistant","partial":"half a li'
    world.write_conversation(body)
    world.capture()
    entry = world.vault.manifests.newest(CONV).main()
    stored = b"".join(restore.read_entry(world.vault.blobs, entry))
    assert stored == body[: body.rindex(b"\n") + 1] and stored.endswith(b"\n")
    assert entry.torn_bytes == len(body) - len(stored) > 0


def test_a_file_that_is_a_placeholder_is_refused_not_recorded_short(tmp_path, monkeypatch):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(10), subagents=0, tool_results=0)
    monkeypatch.setattr("src.cplugs.save.vault.ingest.dataless.is_dataless_stat", lambda st: st.st_ino == main.stat().st_ino)
    with pytest.raises(DatalessSource):
        ingest_file(world.vault.blobs, main, role="transcript", home="claude", rel="projects/x/a.jsonl")
    outcome = world.capture()
    assert outcome.status == "failed" and world.vault.manifests.point_ids(CONV) == []


def test_a_file_replaced_while_it_is_read_is_retried_then_refused(tmp_path, monkeypatch):
    import os

    world = World(tmp_path)
    main = world.write_conversation(b'{"a":1}\n' * 10, subagents=0, tool_results=0)
    import types

    real = os.stat
    calls = {"n": 0}

    def flaky(path, *a, **k):
        st = real(path, *a, **k)
        if str(path) == str(main):
            calls["n"] += 1
            if calls["n"] % 2 == 0:
                fields = {n: getattr(st, n) for n in dir(st) if n.startswith("st_")}
                return types.SimpleNamespace(**{**fields, "st_size": 1})
        return st

    monkeypatch.setattr("src.cplugs.save.vault.ingest.os.stat", flaky)
    with pytest.raises(SourceUnstable):
        ingest_file(world.vault.blobs, main, role="transcript", home="claude", rel="p/a.jsonl")


def test_files_the_original_lost_are_carried_forward_into_the_next_point(tmp_path):
    world = World(tmp_path)
    main = world.write_conversation(jsonl(20), subagents=2, tool_results=0)
    world.capture()
    gone = main.parent / CONV / "subagents" / "agent-0.jsonl"
    gone.unlink()
    with open(main, "ab") as handle:
        handle.write(jsonl(2, seed=5))
    assert world.capture().status == "written"
    rels = {f.rel for f in world.vault.manifests.newest(CONV).files}
    assert f"projects/{ENC}/{CONV}/subagents/agent-0.jsonl" in rels


def test_chunk_reader_is_deterministic_whatever_the_read_size(tmp_path, monkeypatch):
    import io

    data = jsonl(500)
    monkeypatch.setattr(chunking, "CHUNK_TARGET_BYTES", 5000)
    a = [hashlib.sha256(c).hexdigest() for c in ChunkReader(io.BytesIO(data), len(data), True, 5000)]
    monkeypatch.setattr(chunking, "READ_BYTES", 777)
    b = [hashlib.sha256(c).hexdigest() for c in ChunkReader(io.BytesIO(data), len(data), True, 5000)]
    assert a == b and len(a) > 5
    assert b"".join(ChunkReader(io.BytesIO(data), len(data), True, 5000)) == data


from __future__ import annotations

import hashlib
import io
import json
from typing import List, Tuple

import pytest

from src.core.blobcodec.chunking import ChunkReader, ChunkRef, chain_sha
from src.core.blobcodec.codec import (BlobCorrupt, blob_relpath, codec_library, compress, decompress, decompress_bounded,
                                     default_codec)
from src.cplugs.sdk import blob_codec as sdk_blob_codec

MiB = 1024 * 1024

JSONL_PINS = (
    [1048799, 2097400, 2412018],
    ["8342021ffa921de19b37df80009350814da41eb297a3e2ab5dc6d61edd151d04",
     "ed814086dc2a99a440b885f5b145e14ecf8bcab0343257eea0b3185397fe8f33",
     "6fe6ada4dc1937475b714ec65b3127dbfe77f7befff379947d8a21ad69175f35"],
    "69c270c1f983fe32dce82b75f43f5ee5c9884fdf9eb5008c32217b81c198c39b",
)
JSONL_SHA = "10ba7b069a0288639071a4364c4cbb192c3a2cbf7503c53edcc1b47732d333f1"
BINARY_PINS = (
    [1048576, 2097152, 2306867],
    ["6623050ff0d694c5a868c9e038159166c6057c0d167706315e4a1453b5cfccc2",
     "74e26c2f223e81040e77180b676503e474a2ffce0208049624a42a10f91e43aa",
     "3dc0b631c0fde7360d3cb63c3502d58bb58df8888654a8b3debba64c3f8bbd90"],
    "de84a703a9689120163ba87c2dc5f600ccfc91aae992624e37bc68c7b3b74e43",
)
BINARY_SHA = "28e2f6f2c4fd928a2cf8332f32c9070e990378f1a0242a4e06748f0520595fb0"


def jsonl_input(total: int) -> bytes:
    out, i = bytearray(), 0
    while len(out) < total:
        digest = hashlib.sha256(b"line:%d" % i).hexdigest()
        text = digest * (1 + int(digest[:2], 16) % 12)
        out += json.dumps({"i": i, "type": "user", "text": text}, separators=(",", ":")).encode("ascii") + b"\n"
        i += 1
    return bytes(out)


def binary_input(total: int) -> bytes:
    out, i = bytearray(), 0
    while len(out) < total:
        out += hashlib.sha256(b"bin:%d" % i).digest()
        i += 1
    return bytes(out[:total])


def cut(data: bytes, line_mode: bool) -> Tuple[List[int], List[str], str]:
    chunks = list(ChunkReader(io.BytesIO(data), len(data), line_mode))
    offsets, pos = [], 0
    for chunk in chunks:
        pos += len(chunk)
        offsets.append(pos)
    refs = [ChunkRef(hashlib.sha256(c).hexdigest(), len(c)) for c in chunks]
    return offsets, [r.sha256 for r in refs], chain_sha(refs)


@pytest.fixture(scope="module")
def jsonl_data() -> bytes:
    data = jsonl_input(int(2.3 * MiB))
    assert hashlib.sha256(data).hexdigest() == JSONL_SHA, "the JSONL generator changed, not the codec"
    return data


@pytest.fixture(scope="module")
def binary_data() -> bytes:
    data = binary_input(int(2.2 * MiB))
    assert hashlib.sha256(data).hexdigest() == BINARY_SHA, "the binary generator changed, not the codec"
    return data


def test_jsonl_cut_points_and_hashes_are_pinned(jsonl_data):
    assert cut(jsonl_data, True) == JSONL_PINS


def test_binary_cut_points_and_hashes_are_pinned(binary_data):
    assert cut(binary_data, False) == BINARY_PINS


def test_red_control_one_changed_byte_moves_a_pin(jsonl_data):
    offsets, shas, chain = JSONL_PINS
    position = offsets[0] + 100
    assert jsonl_data[position:position + 1] not in (b"\n", b"")
    changed = bytearray(jsonl_data)
    changed[position] = ord("Z") if changed[position] != ord("Z") else ord("Y")
    new_offsets, new_shas, new_chain = cut(bytes(changed), True)
    assert new_offsets == offsets
    assert new_shas[0] == shas[0] and new_shas[2] == shas[2]
    assert new_shas[1] != shas[1]
    assert new_chain != chain


def test_rejoined_chunks_are_the_input(jsonl_data, binary_data):
    assert b"".join(ChunkReader(io.BytesIO(jsonl_data), len(jsonl_data), True)) == jsonl_data
    assert b"".join(ChunkReader(io.BytesIO(binary_data), len(binary_data), False)) == binary_data


@pytest.mark.parametrize("codec", ["zstd", "lzma"])
def test_codec_round_trip(codec, jsonl_data):
    raw = jsonl_data[: MiB]
    assert decompress(compress(raw, codec), codec) == raw


def test_default_codec_is_zstd_on_this_interpreter():
    assert default_codec() == "zstd"


@pytest.mark.parametrize("codec", ["zstd", "lzma"])
def test_decompress_bounded_refuses_a_bomb(codec):
    packed = compress(bytes(10 * MiB), codec)
    assert len(packed) < 64 * 1024
    with pytest.raises(BlobCorrupt):
        decompress_bounded(packed, codec, MiB)


@pytest.mark.parametrize("codec", ["zstd", "lzma"])
def test_decompress_bounded_accepts_exactly_its_length(codec, binary_data):
    raw = binary_data[: MiB]
    assert decompress_bounded(compress(raw, codec), codec, MiB) == raw


@pytest.mark.parametrize("codec", ["zstd", "lzma"])
def test_decompress_bounded_refuses_truncation_and_trailing_bytes(codec, jsonl_data):
    packed = compress(jsonl_data[: MiB], codec)
    with pytest.raises(BlobCorrupt):
        decompress_bounded(packed[:-8], codec, MiB)
    with pytest.raises(BlobCorrupt):
        decompress_bounded(packed + b"tail", codec, MiB)
    with pytest.raises(BlobCorrupt):
        decompress_bounded(b"not a stream at all", codec, MiB)


def test_decompress_bounded_rejects_an_unknown_codec_and_a_negative_bound():
    with pytest.raises(ValueError):
        decompress_bounded(b"", "brotli", 1)
    with pytest.raises(ValueError):
        decompress_bounded(b"", "zstd", -1)


def test_blob_relpath():
    sha = "ab" + "0" * 62
    assert blob_relpath(sha, "zstd") == f"blobs/ab/{sha}.zst"
    assert blob_relpath(sha, "lzma") == f"blobs/ab/{sha}.xz"
    with pytest.raises(KeyError):
        blob_relpath(sha, "brotli")


def test_codec_library_names_the_zstd_version():
    parts = codec_library().split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_the_sdk_seam_is_the_same_objects():
    assert sdk_blob_codec.ChunkReader is ChunkReader and sdk_blob_codec.chain_sha is chain_sha
    assert sdk_blob_codec.decompress_bounded is decompress_bounded
    assert set(sdk_blob_codec.__all__) <= set(dir(sdk_blob_codec))

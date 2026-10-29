
from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from src.core.blobcodec.codec import decompress
from src.core.crate_format.constants import M_MAGIC, MAGIC, MAX_CHUNK_LENGTH
from src.core.crate_format.errors import UnsafeName
from src.core.crate_format.tarsink import CrateSink, content_id_of
from tests.python.crate_format.helpers import EPOCH, build_crate


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    a = build_crate(tmp_path / "a.crate")
    b = build_crate(tmp_path / "b.crate")
    assert a.read_bytes() == b.read_bytes()


def test_headers_are_fixed_and_no_pax_header_is_written(tmp_path: Path) -> None:
    path = build_crate(tmp_path / "a.crate")
    with tarfile.open(path, "r:") as tar:
        members = tar.getmembers()
    assert members[0].name == "CRATE" and members[-1].name == "crate.json"
    for m in members:
        assert (m.type, m.mode, m.uid, m.gid, m.uname, m.gname, m.mtime) == (
            tarfile.REGTYPE, 0o644, 0, 0, "", "", EPOCH)
        assert m.pax_headers == {}
    assert b"PaxHeader" not in path.read_bytes()


def test_blobs_are_written_once_and_hold_their_chunk() -> None:
    out = io.BytesIO()
    sink = CrateSink(out, EPOCH, "zstd")
    sink.add_member(M_MAGIC, MAGIC)
    first = sink.add_blob(b"same chunk")
    second = sink.add_blob(b"same chunk")
    sink.add_blob(b"other")
    sink.close()
    assert first == second and len(sink.blob_names()) == 2
    assert sink.blobs_block()["count"] == 2
    with tarfile.open(fileobj=io.BytesIO(out.getvalue()), mode="r:") as tar:
        packed = tar.extractfile(sink.blob_names()[0]).read()
    assert decompress(packed, "zstd") == b"same chunk"
    assert sink.blob_names()[0] == f"blobs/{first.sha256[:2]}/{first.sha256}.zst"


def test_add_stream_checks_its_size() -> None:
    sink = CrateSink(io.BytesIO(), EPOCH, "zstd")
    record = sink.add_stream("files.jsonl", [b"ab", b"cd"], 4)
    assert record.sha256 == hashlib.sha256(b"abcd").hexdigest()
    with pytest.raises(ValueError):
        sink.add_stream("paths.jsonl", [b"ab"], 4)
    sink = CrateSink(io.BytesIO(), EPOCH, "zstd")
    with pytest.raises(ValueError):
        sink.add_stream("paths.jsonl", [b"abcdef"], 4)


def test_sink_refuses_bad_names_duplicates_and_bad_chunks() -> None:
    sink = CrateSink(io.BytesIO(), EPOCH, "lzma")
    with pytest.raises(UnsafeName):
        sink.add_member("../x", b"")
    with pytest.raises(UnsafeName):
        sink.add_member("future/member", b"")
    sink.add_member("README.txt", b"x")
    with pytest.raises(ValueError):
        sink.add_member("README.txt", b"x")
    with pytest.raises(ValueError):
        sink.add_blob(b"")
    with pytest.raises(ValueError):
        sink.add_blob(b"\0" * (MAX_CHUNK_LENGTH + 1))
    sink.close()
    with pytest.raises(ValueError):
        sink.add_member("files.jsonl", b"")


def test_lzma_blobs_use_xz(tmp_path: Path) -> None:
    path = build_crate(tmp_path / "a.crate", codec="lzma")
    with tarfile.open(path, "r:") as tar:
        blobs = [n for n in tar.getnames() if n.startswith("blobs/")]
    assert blobs and all(n.endswith(".xz") for n in blobs)


def test_content_id_ignores_codec(tmp_path: Path) -> None:
    from src.core.crate_format.reader import open_crate

    with open_crate(build_crate(tmp_path / "z.crate")) as z, open_crate(
            build_crate(tmp_path / "x.crate", codec="lzma")) as x:
        assert z.manifest.content_id == x.manifest.content_id
        assert content_id_of(z.manifest.members) == z.manifest.content_id


def test_a_long_rows_name_gets_a_pax_path_header_and_reads_back() -> None:
    name = "rows/" + "a" * 40 + "/" + "T" * 64 + ".0001.jsonl"
    out = io.BytesIO()
    sink = CrateSink(out, EPOCH, "zstd")
    sink.add_member(M_MAGIC, MAGIC)
    sink.add_member(name, b'{"x":1}\n')
    sink.close()
    data = out.getvalue()
    assert len(name) == 121 and b"path=" + name.encode() in data
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        assert [m.name for m in tar.getmembers()] == [M_MAGIC, name]
        assert tar.getmember(name).pax_headers.get("path") == name


from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, List

import pytest

from src.core.crate_format import reader as reader_module
from src.core.crate_format import verify_full
from src.core.crate_format.errors import CrateMalformed
from src.core.crate_format.reader import open_crate
from src.core.crate_format.verify import verify
from tests.python.crate_format import mutate
from tests.python.crate_format.helpers import build_crate

Pairs = List[mutate.Pair]
DEEP = b"[" * 200_000 + b"]" * 200_000


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _broken(tmp_path: Path, change: Callable[[Pairs], None]) -> Path:
    pairs = mutate.entries(build_crate(tmp_path / "good.crate"))
    change(pairs)
    return mutate.write(pairs, tmp_path / "bad.crate")


@pytest.mark.parametrize("level", ["quick", "full"])
def test_a_deeply_nested_manifest_is_malformed_not_a_crash(tmp_path: Path, level: str) -> None:
    def change(pairs: Pairs) -> None:
        mutate.find(pairs, "crate.json")[1] = DEEP

    bad = _broken(tmp_path, change)
    report = verify(bad, level, _sha(bad))
    assert report.codes == ["malformed"] and "nested too deeply" in report.problems[0]["detail"]


def test_a_deeply_nested_files_line_is_malformed_not_a_crash(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        pair = mutate.find(pairs, "files.jsonl")
        lines = pair[1].splitlines(keepends=True)
        pair[1] = DEEP + b"\n" + b"".join(lines[1:])
        mutate.reseal(pairs)

    bad = _broken(tmp_path, change)
    report = verify(bad, "full", _sha(bad))
    assert "malformed" in report.codes and not report.ok


def test_a_twin_blob_for_one_chunk_is_refused(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        name = mutate.find(pairs, "blob")[0].name
        twin = name.rsplit(".", 1)[0] + ".xz"
        mutate.insert_before_manifest(pairs, mutate.info(twin), b"garbage bytes, never a valid xz stream")
        mutate.reseal(pairs)

    bad = _broken(tmp_path, change)
    report = verify(bad, "full", _sha(bad))
    assert report.codes == ["malformed"] and "stored twice" in report.problems[0]["detail"]


def test_blobs_codecs_must_match_the_blob_extensions(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        obj = mutate.manifest(pairs)
        obj["blobs"]["codecs"] = ["lzma"] if obj["blobs"]["codecs"] == ["zstd"] else ["zstd"]
        mutate.set_manifest(pairs, obj)

    bad = _broken(tmp_path, change)
    report = verify(bad, "quick", _sha(bad))
    assert report.codes == ["member_mismatch"] and "codecs" in report.problems[0]["detail"]


def test_a_rows_part_over_its_cap_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good = build_crate(tmp_path / "good.crate")
    monkeypatch.setattr(reader_module, "MAX_ROWS_PART", 8)
    with pytest.raises(CrateMalformed, match="larger than 8 bytes"):
        open_crate(good)


def test_a_rows_line_over_its_bound_is_malformed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    good = build_crate(tmp_path / "good.crate")
    assert verify(good, "full", _sha(good)).ok
    monkeypatch.setattr(reader_module, "MAX_ROWS_LINE", 4)
    monkeypatch.setattr(verify_full, "MAX_ROWS_LINE", 4)
    report = verify(good, "full", _sha(good))
    assert report.codes == ["malformed"] and "longer than 4 bytes" in report.problems[0]["detail"]
    with open_crate(good) as reader:
        store, tables = next(iter(reader.tables().items()))
        with pytest.raises(CrateMalformed, match="longer than 4 bytes"):
            list(reader.rows(store, next(iter(tables))))


def test_iter_lines_splits_across_small_reads_and_keeps_a_last_line_without_newline(tmp_path: Path) -> None:
    good = build_crate(tmp_path / "good.crate")
    with open_crate(good) as reader:
        whole = reader.read_member("files.jsonl")
        normal = list(reader.iter_lines("files.jsonl"))
        small = reader.iter_member
        reader.iter_member = lambda name: small(name, 7)
        assert list(reader.iter_lines("files.jsonl")) == normal
        assert b"".join(normal) == whole and all(line.endswith(b"\n") for line in normal)

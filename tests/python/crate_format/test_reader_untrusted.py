
from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Callable, List

import pytest

from src.core.blobcodec.codec import compress
from src.core.crate_format import reader as reader_module
from src.core.crate_format.constants import MAX_CHUNK_LENGTH
from src.core.crate_format.errors import CrateCorrupt, CrateError, CrateMalformed, UnsafeName
from src.core.crate_format.extract import extract_all
from src.core.crate_format.reader import open_crate
from tests.python.crate_format import mutate
from tests.python.crate_format.helpers import build_crate

Pairs = List[mutate.Pair]


def _attempt(tmp_path: Path, change: Callable[[Pairs], None]) -> CrateError:
    src = build_crate(tmp_path / "good.crate")
    pairs = mutate.entries(src)
    change(pairs)
    bad = mutate.write(pairs, tmp_path / "bad.crate")
    dest = tmp_path / "out"
    with pytest.raises(CrateError) as caught:
        with open_crate(bad) as reader:
            extract_all(reader, dest)
    assert not dest.exists()
    return caught.value


def _add(name: str, kind: bytes = tarfile.REGTYPE, linkname: str = "") -> Callable[[Pairs], None]:
    return lambda pairs: mutate.insert_before_manifest(pairs, mutate.info(name, 0, kind, linkname), b"")


@pytest.mark.parametrize("change", [
    _add("../x"), _add("/etc/x"), _add("blobs/zz/" + "a" * 64 + ".zst"), _add("rows/../x.jsonl"),
    _add("blobs/ab/" + "cd" * 32 + ".zst"),
], ids=["dotdot", "absolute", "bad-blob-hex", "rows-dotdot", "blob-folder-mismatch"])
def test_unsafe_names_are_refused(tmp_path: Path, change) -> None:
    assert isinstance(_attempt(tmp_path, change), UnsafeName)


@pytest.mark.parametrize("kind,link", [(tarfile.SYMTYPE, "/etc/passwd"), (tarfile.LNKTYPE, "README.txt"),
                                       (tarfile.CHRTYPE, ""), (tarfile.DIRTYPE, ""), (tarfile.FIFOTYPE, "")],
                         ids=["symlink", "hardlink", "device", "directory", "fifo"])
def test_non_regular_members_are_refused(tmp_path: Path, kind, link) -> None:
    err = _attempt(tmp_path, _add("lines/claude-history-1.jsonl", kind, link))
    assert isinstance(err, CrateMalformed) and "not a regular file" in str(err)


def test_a_symlink_named_like_a_real_member_is_refused(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        pair = mutate.find(pairs, "paths.jsonl")
        pair[0] = mutate.info("paths.jsonl", 0, tarfile.SYMTYPE, "/etc/passwd")
    assert "not a regular file" in str(_attempt(tmp_path, change))


def test_a_duplicate_member_is_refused(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        mutate.insert_before_manifest(pairs, mutate.info("README.txt"), b"again")
    assert "twice" in str(_attempt(tmp_path, change))


_MAGIC_CHANGES = {
    "missing": (lambda pairs: pairs.pop(0), "first member"),
    "not-first": (lambda pairs: pairs.insert(1, pairs.pop(0)), "first member"),
    "wrong-bytes": (lambda pairs: pairs[0].__setitem__(1, b"carnivore-crate 2\n"), "magic"),
}


@pytest.mark.parametrize("which", sorted(_MAGIC_CHANGES))
def test_crate_magic_missing_not_first_or_wrong(tmp_path: Path, which: str) -> None:
    change, words = _MAGIC_CHANGES[which]
    assert words in str(_attempt(tmp_path, change))


def test_manifest_not_last_is_refused(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        pairs.insert(3, pairs.pop())
    assert "last member" in str(_attempt(tmp_path, change))


def test_an_oversize_json_member_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reader_module, "MAX_JSON_MEMBER", 64)
    assert "larger than 64" in str(_attempt(tmp_path, lambda pairs: None))


def test_too_many_members_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reader_module, "MAX_MEMBERS", 5)
    assert "more than 5" in str(_attempt(tmp_path, lambda pairs: None))


def test_a_truncated_container_is_refused(tmp_path: Path) -> None:
    src = build_crate(tmp_path / "good.crate")
    data = src.read_bytes()
    cut = tmp_path / "cut.crate"
    cut.write_bytes(data[:len(data) // 2])
    with pytest.raises(CrateMalformed):
        open_crate(cut)


def test_a_bomb_blob_is_refused_and_nothing_is_left(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        pair = mutate.find(pairs, "blob")
        pair[1] = compress(b"\0" * (10 * 1024 * 1024), "zstd" if pair[0].name.endswith(".zst") else "lzma")
    err = _attempt(tmp_path, change)
    assert isinstance(err, CrateCorrupt) and err.code == "blob_corrupt"
    assert "inflates past its stated length" in str(err)


def test_dotdot_in_a_rel_is_refused(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        def edit(records):
            records[0]["rel"] = "../../escape.txt"
        mutate.edit_files(pairs, edit)
    assert isinstance(_attempt(tmp_path, change), UnsafeName)


def test_an_unsafe_home_is_refused(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        def edit(records):
            records[0]["home"] = ".."
        mutate.edit_files(pairs, edit)
    assert isinstance(_attempt(tmp_path, change), UnsafeName)


def test_a_chunk_length_over_the_cap_is_refused(tmp_path: Path) -> None:
    def change(pairs: Pairs) -> None:
        def edit(records):
            records[0]["chunks"][0][1] = MAX_CHUNK_LENGTH + 1
        mutate.edit_files(pairs, edit)
    assert "chunk length" in str(_attempt(tmp_path, change))


def test_the_good_crate_opens_and_extracts(tmp_path: Path) -> None:
    src = build_crate(tmp_path / "good.crate")
    with open_crate(src) as reader:
        result = extract_all(reader, tmp_path / "out")
    assert len(result.files) == 8 and (tmp_path / "out").is_dir()

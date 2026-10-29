
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.core.crate_format.constants import FORMAT_MINOR
from src.core.crate_format.errors import CrateMalformed, CrateTooNew, UnsafeName
from src.core.crate_format.extract import extract_all
from src.core.crate_format.promise import check_readable
from src.core.crate_format.reader import open_crate
from src.core.crate_format.verify import verify
from tests.python.crate_format import mutate
from tests.python.crate_format.helpers import SrcFile, build_crate, default_files

UNKNOWN = "attachments/v11/one.bin"


@pytest.mark.parametrize("version,result", [([1, 0], (1, 0)), ([1, 7], (1, 7))])
def test_known_major_any_minor(version, result) -> None:
    assert check_readable({"format": "carnivore-crate", "format_version": version}) == result


def test_newer_major_is_too_new() -> None:
    with pytest.raises(CrateTooNew) as caught:
        check_readable({"format": "carnivore-crate", "format_version": [2, 0]})
    assert caught.value.major == 2 and "newer Carnivore" in str(caught.value)


@pytest.mark.parametrize("obj", [[], {"format": "x", "format_version": [1, 0]}, {"format": "carnivore-crate"},
                                 {"format": "carnivore-crate", "format_version": [1]},
                                 {"format": "carnivore-crate", "format_version": [True, 0]},
                                 {"format": "carnivore-crate", "format_version": [0, 1]},
                                 {"format": "carnivore-crate", "format_version": [1, -1]}])
def test_malformed_identity(obj) -> None:
    with pytest.raises(CrateMalformed):
        check_readable(obj)


def _v11(tmp_path: Path, listed: bool) -> Path:
    files = default_files() + [SrcFile("hologram", "vault", "deep/thing.bin", b"future bytes", None, family=None)]
    pairs = mutate.entries(build_crate(tmp_path / "base.crate", files=files, minor=FORMAT_MINOR + 1,
                                       extra_manifest={"future_key": {"x": 1}}))
    mutate.insert_before_manifest(pairs, mutate.info(UNKNOWN), b"new kind of member")
    if listed:
        mutate.reseal(pairs)
    return mutate.write(pairs, tmp_path / "v11.crate")


def test_v1_0_reader_reads_a_v1_1_crate(tmp_path: Path) -> None:
    path = _v11(tmp_path, listed=True)
    report = verify(path, "full", hashlib.sha256(path.read_bytes()).hexdigest())
    assert report.ok, report.problems
    with open_crate(path) as reader:
        assert reader.unknown_members() == [UNKNOWN]
        assert reader.manifest.extra == {"future_key": {"x": 1}}
        result = extract_all(reader, tmp_path / "out")
    assert (tmp_path / "out" / "vault" / "deep" / "thing.bin").read_bytes() == b"future bytes"
    assert UNKNOWN not in result.files and not (tmp_path / "out" / "attachments").exists()


def test_v1_1_unknown_member_left_unlisted_is_extra_member(tmp_path: Path) -> None:
    path = _v11(tmp_path, listed=False)
    report = verify(path, "full", hashlib.sha256(path.read_bytes()).hexdigest())
    assert "extra_member" in report.codes


def test_unknown_member_at_minor_0_is_refused(tmp_path: Path) -> None:
    pairs = mutate.entries(build_crate(tmp_path / "base.crate"))
    mutate.insert_before_manifest(pairs, mutate.info(UNKNOWN), b"x")
    mutate.reseal(pairs)
    with pytest.raises(UnsafeName):
        open_crate(mutate.write(pairs, tmp_path / "bad.crate"))


def test_unsafe_name_is_refused_at_any_minor(tmp_path: Path) -> None:
    pairs = mutate.entries(build_crate(tmp_path / "base.crate", minor=9))
    mutate.insert_before_manifest(pairs, mutate.info("Attachments/../x"), b"x")
    with pytest.raises(UnsafeName):
        open_crate(mutate.write(pairs, tmp_path / "bad.crate"))

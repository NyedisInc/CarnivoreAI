
from __future__ import annotations

import hashlib
import stat
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.crate_format.errors import CrateMalformed
from src.core.crate_format.extract import extract_all
from src.core.crate_format.reader import open_crate
from src.core.crate_format.verify import verify
from tests.python.crate_format import mutate
from tests.python.crate_format.helpers import build_crate


def _crate_with(tmp_path: Path, field: str, value: Any) -> Path:
    pairs = mutate.entries(build_crate(tmp_path / "good.crate"))

    def change(records: List[Dict[str, Any]]) -> None:
        records[0][field] = value

    mutate.edit_files(pairs, change)
    return mutate.write(pairs, tmp_path / "meta.crate")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_mode_without_owner_read_still_drills_and_extracts(tmp_path: Path) -> None:
    path = _crate_with(tmp_path, "mode", 0o200)
    assert verify(path, "full", _sha(path)).ok
    report = verify(path, "drill", _sha(path), scratch=tmp_path / "scratch")
    assert report.ok, report.problems
    with open_crate(path) as reader:
        first = reader.files()[0]
        result = extract_all(reader, tmp_path / "out")
    written = result.dest / first.place
    assert stat.S_IMODE(written.stat().st_mode) == 0o200


def test_an_out_of_range_mtime_is_reported_not_raised(tmp_path: Path) -> None:
    path = _crate_with(tmp_path, "mtime_ns", 10 ** 30)
    assert verify(path, "full", _sha(path)).ok
    report = verify(path, "drill", _sha(path), scratch=tmp_path / "scratch")
    assert report.codes == ["malformed"] and "mtime" in report.problems[0]["detail"]
    with open_crate(path) as reader:
        with pytest.raises(CrateMalformed, match="mtime"):
            extract_all(reader, tmp_path / "out")
    assert not (tmp_path / "out").exists()


from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

import pytest

from src.core.crate_format.errors import CrateCorrupt
from src.core.crate_format.reader import CrateReader
from src.core.crate_format.verify import verify
from tests.python.crate_format.helpers import build_crate


def test_a_corrupt_member_read_is_a_problem_not_an_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = build_crate(tmp_path / "a.crate")

    def broken(self: CrateReader, name: str, block: int = 0) -> Iterator[bytes]:
        raise CrateCorrupt(["a middle age chunk failed authentication"], code="age_corrupt")
        yield b""

    monkeypatch.setattr(CrateReader, "iter_member", broken)
    report = verify(path, "full", hashlib.sha256(path.read_bytes()).hexdigest())
    assert not report.ok and "age_corrupt" in report.codes

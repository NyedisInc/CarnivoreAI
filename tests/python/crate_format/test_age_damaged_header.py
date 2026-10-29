
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from src.core.crate_crypto.age_header import parse_header
from src.core.crate_crypto.keys import generate
from src.core.crate_format.__main__ import EXIT_PROBLEMS, main
from src.core.crate_format.verify import verify
from tests.python.crate_format.helpers import build_crate


def _damaged(tmp_path: Path) -> tuple:
    identity, recipient = generate()
    path = build_crate(tmp_path / "a.crate.age", recipients=[recipient])
    data = bytearray(path.read_bytes())
    header = parse_header(bytes(data[:4096]))
    data[header.length - 3] ^= 0x01
    bad = tmp_path / "bad.crate.age"
    bad.write_bytes(bytes(data))
    return bad, identity


def test_verify_reports_age_corrupt_not_wrong_key(tmp_path: Path) -> None:
    bad, identity = _damaged(tmp_path)
    report = verify(bad, "full", hashlib.sha256(bad.read_bytes()).hexdigest(), identity=identity)
    assert report.codes == ["age_corrupt"] and "MAC" in report.problems[0]["detail"]


def test_the_cli_exits_1_for_a_damaged_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad, identity = _damaged(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(identity))
    sha = hashlib.sha256(bad.read_bytes()).hexdigest()
    assert main(["verify", str(bad), "--sha", sha, "--identity-stdin"]) == EXIT_PROBLEMS

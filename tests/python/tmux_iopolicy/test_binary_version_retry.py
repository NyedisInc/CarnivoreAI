
from __future__ import annotations

import os
import stat
from pathlib import Path

from src.core import tmux_discovery as td


def _stand_in(tmp_path: Path) -> str:
    binary = tmp_path / "tmux"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return str(binary)


def test_a_failed_version_probe_is_asked_again_and_a_measured_one_is_kept(tmp_path, monkeypatch):
    path = _stand_in(tmp_path)
    td.reset_probe_cache()
    answers = [None, (0, "tmux 3.7c\n", ""), (0, "tmux 9.9\n", "")]
    calls: list = []

    def fake(argv):
        calls.append(argv)
        return answers.pop(0)

    monkeypatch.setattr(td, "_run_text", fake)
    try:
        assert td.binary_version(path) is None
        assert td.binary_version(path) == "3.7c"
        assert td.binary_version(path) == "3.7c"
        assert len(calls) == 2
        os.utime(path, ns=(1, 1))
        assert td.binary_version(path) == "9.9"
    finally:
        td.reset_probe_cache()

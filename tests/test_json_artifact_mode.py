
from __future__ import annotations

import os
import stat
from pathlib import Path

from src.core.json_artifact import atomic_write_json


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_default_mode_is_0600_under_a_022_umask(tmp_path: Path) -> None:
    previous = os.umask(0o022)
    try:
        target = tmp_path / "state.json"
        assert atomic_write_json(target, {"a": 1}, log_event="t")
    finally:
        os.umask(previous)
    assert _mode(target) == 0o600


def test_a_caller_can_ask_for_a_wider_mode(tmp_path: Path) -> None:
    previous = os.umask(0o077)
    try:
        target = tmp_path / "shared.json"
        assert atomic_write_json(target, {}, log_event="t", mode=0o644)
    finally:
        os.umask(previous)
    assert _mode(target) == 0o644


from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from src.core.server_log import locate, self_rotate


def _live(tmp_path: Path) -> Path:
    path = tmp_path / "logs" / "server.log"
    path.parent.mkdir()
    return path


def test_copy_truncate_keeps_an_append_writer_going_and_the_backup_private(tmp_path: Path) -> None:
    path = _live(tmp_path)
    writer = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.write(writer, b"a" * 4096)
    assert self_rotate.rotate_if_needed(path, max_bytes=1024, backups=5) is True
    backup = Path(f"{path}.1")
    assert backup.read_bytes() == b"a" * 4096
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert path.stat().st_size == 0
    os.write(writer, b"after\n")
    os.close(writer)
    assert path.read_bytes() == b"after\n"
    assert not list(path.parent.glob(".*.tmp"))


def test_under_the_cap_or_missing_is_a_no_op(tmp_path: Path) -> None:
    path = _live(tmp_path)
    assert self_rotate.rotate_if_needed(path, max_bytes=10) is False
    path.write_bytes(b"x" * 10)
    assert self_rotate.rotate_if_needed(path, max_bytes=10) is False
    assert not Path(f"{path}.1").exists()


def test_five_backups_and_the_oldest_falls_off(tmp_path: Path) -> None:
    path = _live(tmp_path)
    for generation in range(1, 8):
        path.write_bytes(f"gen{generation}".encode() + b"." * 100)
        assert self_rotate.rotate_if_needed(path, max_bytes=50, backups=5) is True
    assert [Path(f"{path}.{i}").read_bytes()[:4] for i in range(1, 6)] == [b"gen7", b"gen6", b"gen5", b"gen4", b"gen3"]
    assert not Path(f"{path}.6").exists()


def test_a_real_sized_file_rotates_at_the_shipped_cap(tmp_path: Path) -> None:
    path = _live(tmp_path)
    with path.open("wb") as handle:
        handle.truncate(self_rotate.MAX_BYTES + 1024 * 1024)
    assert self_rotate.rotate_if_needed(path) is True
    assert Path(f"{path}.1").stat().st_size == self_rotate.MAX_BYTES + 1024 * 1024
    assert path.stat().st_size == 0


def test_a_symlinked_log_is_refused_not_followed(tmp_path: Path) -> None:
    target = tmp_path / "victim.txt"
    target.write_bytes(b"v" * 100)
    path = _live(tmp_path)
    path.symlink_to(target)
    assert self_rotate.rotate_if_needed(path, max_bytes=10) is False
    assert target.read_bytes() == b"v" * 100


def test_only_the_desktop_apps_server_log_is_rotated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    mine = locate.menubar_log_files()[0]
    mine.parent.mkdir(parents=True)
    for raw, expected in ((str(mine), mine), (str(locate.dev_log_file()), None), ("/etc/passwd", None)):
        locate.own_log_path.cache_clear()
        monkeypatch.setenv("CARNIVORE_LOG_FILE", raw)
        assert self_rotate.applicable_path() == expected
    locate.own_log_path.cache_clear()
    monkeypatch.delenv("CARNIVORE_LOG_FILE")
    assert self_rotate.applicable_path() is None
    locate.own_log_path.cache_clear()

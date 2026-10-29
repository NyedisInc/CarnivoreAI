
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Callable

import pytest

from src.core.safe_io import atomic_write as aw
from src.core.safe_io.atomic_write import atomic_write_bytes, atomic_write_text


def _entries(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def test_writes_text_and_bytes(tmp_path: Path) -> None:
    atomic_write_text(tmp_path / "a.txt", "héllo")
    atomic_write_bytes(tmp_path / "b.bin", b"\x00\x01")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "héllo"
    assert (tmp_path / "b.bin").read_bytes() == b"\x00\x01"
    assert _entries(tmp_path) == ["a.txt", "b.bin"]


def test_mode_is_exact_and_parents_made(tmp_path: Path) -> None:
    target = tmp_path / "d" / "f"
    previous = os.umask(0o022)
    try:
        atomic_write_bytes(target, b"x", mode=0o600, parent_mode=0o700)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


def test_fsyncs_the_file_and_the_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = os.fsync
    kinds: list[str] = []

    def spy(fd: int) -> None:
        kinds.append("dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        real(fd)

    monkeypatch.setattr(aw.os, "fsync", spy)
    atomic_write_bytes(tmp_path / "x", b"1")
    assert kinds == ["file", "dir"]


def test_failed_replace_keeps_old_file_and_leaves_no_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "x").write_bytes(b"old")

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("nope")

    monkeypatch.setattr(aw.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(tmp_path / "x", b"new")
    assert (tmp_path / "x").read_bytes() == b"old"
    assert _entries(tmp_path) == ["x"]


def _manifest(p: Path, d: bytes) -> None:
    from src.core.project_pack.manifest import write_atomic
    write_atomic(str(p), d)


def _summary(p: Path, d: bytes) -> None:
    from src.cplugs.save.vault.summary_disk import write_atomic
    write_atomic(p, d)


def _reviewboard(p: Path, d: bytes) -> None:
    from src.cplugs.reviewboard.store import write_atomic
    write_atomic(p, d)


def _hero(p: Path, d: bytes) -> None:
    from src.core.companies.hero_images import atomic_write
    atomic_write(p, d)


@pytest.mark.parametrize("writer", [_manifest, _summary, _reviewboard, _hero])
def test_former_private_copies_share_the_guarantees(
    writer: Callable[[Path, bytes], None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.fsync
    dir_syncs: list[int] = []

    def spy(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            dir_syncs.append(fd)
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    writer(tmp_path / "ok", b"v")
    assert dir_syncs, "directory was never fsynced"

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("nope")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        writer(tmp_path / "fail", b"v")
    assert _entries(tmp_path) == ["ok"]


def _fsync_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    real = os.fsync

    def fake(fd: int) -> None:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(22, "Invalid argument")
        real(fd)

    monkeypatch.setattr(aw.os, "fsync", fake)


def test_unsupported_fsync_is_tolerated_only_when_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fsync_unsupported(monkeypatch)
    atomic_write_bytes(tmp_path / "ok", b"1", tolerate_fsync_unsupported=True)
    assert (tmp_path / "ok").read_bytes() == b"1"
    with pytest.raises(OSError):
        atomic_write_bytes(tmp_path / "strict", b"1")
    assert _entries(tmp_path) == ["ok"]


def test_a_real_fsync_failure_is_never_tolerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def eio(_fd: int) -> None:
        raise OSError(5, "I/O error")

    monkeypatch.setattr(aw.os, "fsync", eio)
    with pytest.raises(OSError):
        atomic_write_bytes(tmp_path / "x", b"1", tolerate_fsync_unsupported=True)

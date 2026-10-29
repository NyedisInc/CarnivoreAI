from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from src.core import safe_file_write
from src.core.safe_file_write import (
    SafeFileWriteError,
    UnsafeFileTargetError,
    write_private_file,
)


def test_writes_exact_bytes_with_exact_mode(tmp_path: Path) -> None:
    out = write_private_file(tmp_path / "d", "run.sh", b"#!/bin/sh\n", 0o700)
    assert out.read_bytes() == b"#!/bin/sh\n"
    assert stat.S_IMODE(out.stat().st_mode) == 0o700


def test_existing_regular_file_is_replaced(tmp_path: Path) -> None:
    d = tmp_path / "d"
    write_private_file(d, "f", b"one", 0o600)
    write_private_file(d, "f", b"two", 0o600)
    assert (d / "f").read_bytes() == b"two"


def test_symlink_target_refused(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir(mode=0o700)
    victim = tmp_path / "victim"
    victim.write_bytes(b"keep")
    (d / "f").symlink_to(victim)
    with pytest.raises(UnsafeFileTargetError) as caught:
        write_private_file(d, "f", b"evil", 0o600)
    assert caught.value.reason == "target_is_symlink"
    assert victim.read_bytes() == b"keep"


def test_directory_at_final_name_refused(tmp_path: Path) -> None:
    d = tmp_path / "d"
    (d / "f").mkdir(parents=True)
    os.chmod(d, 0o700)
    with pytest.raises(UnsafeFileTargetError) as caught:
        write_private_file(d, "f", b"x", 0o600)
    assert caught.value.reason == "target_not_a_regular_file"


def test_symlinked_directory_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(UnsafeFileTargetError) as caught:
        write_private_file(link, "f", b"x", 0o600)
    assert caught.value.reason == "directory_is_symlink"
    assert list(real.iterdir()) == []


def test_file_in_place_of_directory_refused(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.write_bytes(b"")
    with pytest.raises(UnsafeFileTargetError) as caught:
        write_private_file(d, "f", b"x", 0o600)
    assert caught.value.reason == "directory_not_a_directory"


def test_group_writable_directory_refused(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    os.chmod(d, 0o770)
    with pytest.raises(UnsafeFileTargetError) as caught:
        write_private_file(d, "f", b"x", 0o600)
    assert caught.value.reason == "directory_foreign_writable"


def test_foreign_owner_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "d"
    d.mkdir(mode=0o700)
    monkeypatch.setattr(safe_file_write.os, "geteuid", lambda: os.getuid() + 4242)
    with pytest.raises(UnsafeFileTargetError) as caught:
        write_private_file(d, "f", b"x", 0o600)
    assert caught.value.reason == "directory_foreign_owner"


def test_directory_swapped_before_rename_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "d"
    monkeypatch.setattr(safe_file_write, "_still_same_dir", lambda *_: False)
    with pytest.raises(UnsafeFileTargetError) as caught:
        write_private_file(d, "f", b"x", 0o600)
    assert caught.value.reason == "directory_is_symlink"
    assert list(d.iterdir()) == []


def test_io_failure_is_named_and_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "d"

    def boom(*_a: object, **_k: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(safe_file_write.os, "replace", boom)
    with pytest.raises(SafeFileWriteError) as caught:
        write_private_file(d, "f", b"x", 0o600)
    assert not isinstance(caught.value, UnsafeFileTargetError)
    assert list(d.iterdir()) == []


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b"])
def test_rejects_non_plain_names(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        write_private_file(tmp_path, bad, b"x", 0o600)

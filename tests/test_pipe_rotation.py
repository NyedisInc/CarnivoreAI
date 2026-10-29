
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.pipe_rotation import rotation_reason, truncate_in_place


def test_rotation_reason_leaves_a_file_under_both_ceilings_alone():
    assert rotation_reason(9, 1.0, 10, 24.0) is None


def test_rotation_reason_is_strictly_greater_than_not_equal():
    assert rotation_reason(10, 24.0, 10, 24.0) is None
    assert rotation_reason(11, 24.0, 10, 24.0) == "size"
    assert rotation_reason(10, 24.1, 10, 24.0) == "age"


def test_rotation_reason_reports_size_when_both_apply():
    assert rotation_reason(999, 999.0, 10, 24.0) == "size"


@pytest.fixture
def pipe(tmp_path):
    path = tmp_path / "probe.pipe"
    path.touch()
    write_fd = os.open(str(path), os.O_WRONLY | os.O_APPEND)
    read_fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
    try:
        yield path, write_fd, read_fd
    finally:
        os.close(write_fd)
        os.close(read_fd)


def _read_all(fd: int) -> bytes:
    out = b""
    while True:
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            break
        if not chunk:
            break
        out += chunk
    return out


def test_reader_follows_the_trim_and_repeats_nothing(pipe):
    path, write_fd, read_fd = pipe

    os.write(write_fd, b"FIRST_GENERATION_BYTES\n")
    assert _read_all(read_fd) == b"FIRST_GENERATION_BYTES\n"

    assert truncate_in_place(path, read_fd) is True
    assert path.stat().st_size == 0

    os.write(write_fd, b"SECOND_GENERATION_BYTES\n")
    after = _read_all(read_fd)

    assert after == b"SECOND_GENERATION_BYTES\n", (
        "the reader did not land on the trimmed file's first byte"
    )
    assert b"FIRST_GENERATION_BYTES" not in after, (
        "the reader replayed output it had already delivered"
    )


def test_unread_bytes_are_the_callers_problem_not_a_silent_replay(pipe):
    path, write_fd, read_fd = pipe

    os.write(write_fd, b"NEVER_READ_BEFORE_TRIM\n")
    assert truncate_in_place(path, read_fd) is True

    os.write(write_fd, b"POST_TRIM\n")
    assert _read_all(read_fd) == b"POST_TRIM\n"


def test_the_writers_offset_restarts_at_zero(pipe):
    path, write_fd, read_fd = pipe

    os.write(write_fd, b"x" * 5000)
    assert path.stat().st_size == 5000

    assert truncate_in_place(path, read_fd) is True
    os.write(write_fd, b"y" * 10)

    assert path.stat().st_size == 10, (
        "the file re-grew to its old length, so the writer is not O_APPEND"
    )


def test_a_missing_file_refuses_instead_of_raising(tmp_path):
    missing = tmp_path / "gone.pipe"
    real = tmp_path / "real.pipe"
    real.touch()
    read_fd = os.open(str(real), os.O_RDONLY)
    try:
        assert truncate_in_place(missing, read_fd) is False
    finally:
        os.close(read_fd)


def test_a_closed_reader_refuses_after_the_truncate(tmp_path):
    path = tmp_path / "probe.pipe"
    path.write_bytes(b"some bytes")
    read_fd = os.open(str(path), os.O_RDONLY)
    os.close(read_fd)

    assert truncate_in_place(path, read_fd) is False
    assert path.stat().st_size == 0

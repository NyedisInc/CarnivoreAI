
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rot_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rot_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import tmux_backend as tmux_backend_module
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="real tmux binary not available"
)

SMALL_LOG_BYTES = 512

STREAM_TIMEOUT = 10.0


def _tmux(socket: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", "-L", socket, *args],
        capture_output=True,
        text=True,
        timeout=15,
    )


async def _await_text(chunks: List[bytes], needle: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if needle.encode() in b"".join(chunks):
            return True
        await asyncio.sleep(0.05)
    return False


async def _await_rotation(backend: TmuxBackend, before: float, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if backend._rotation_started_at != before:
            return True
        await asyncio.sleep(0.05)
    return False


class _Harness:

    def __init__(self) -> None:
        self.socket = derive_test_socket("rotate")
        self.tmpdir = Path(tempfile.mkdtemp(prefix="cc_rot_"))
        self.pipe_path = self.tmpdir / "pipe.log"
        self.seen: List[bytes] = []
        self.backend: TmuxBackend
        self.task: asyncio.Task

    async def start(self) -> None:
        made = _tmux(
            self.socket, "new-session", "-d", "-s", "probe",
            "-x", "80", "-y", "24", "sh",
        )
        assert made.returncode == 0, f"new-session failed: {made.stderr}"

        self.pipe_path.touch()
        piped = _tmux(
            self.socket, "pipe-pane", "-t", "probe",
            f"cat >> {self.pipe_path}",
        )
        assert piped.returncode == 0, f"pipe-pane failed: {piped.stderr}"

        self.backend = TmuxBackend(
            session_id="rotateprobe",
            working_dir=self.tmpdir,
            on_output=self.seen.append,
            socket_name=self.socket,
            session_name="probe",
        )
        self.backend._pipe_path = self.pipe_path
        self.backend._running = True
        self.task = asyncio.create_task(self.backend._tail_loop())
        await asyncio.sleep(0.6)

    def send(self, line: str) -> None:
        _tmux(self.socket, "send-keys", "-t", "probe", line, "Enter")

    async def stop(self) -> None:
        self.backend._running = False
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        _tmux(self.socket, "kill-server")
        shutil.rmtree(self.tmpdir, ignore_errors=True)


@pytest_asyncio.fixture
async def harness():
    h = _Harness()
    await h.start()
    try:
        yield h
    finally:
        await h.stop()


async def _drive_past_threshold(h: _Harness) -> float:
    before = h.backend._rotation_started_at
    for i in range(12):
        h.send(f"echo FILLER_LINE_{i}_ppppppppppppppppppppppppppppppppppppppp")
        await asyncio.sleep(0.05)
    return before


@pytest.mark.asyncio
async def test_stream_survives_a_rotation(harness, monkeypatch):
    monkeypatch.setattr(tmux_backend_module, "MAX_LOG_BYTES", SMALL_LOG_BYTES)
    h = harness

    h.send("echo MARKER_BEFORE_ROT")
    assert await _await_text(h.seen, "MARKER_BEFORE_ROT", STREAM_TIMEOUT), (
        "the tail loop never delivered output before any rotation, so the "
        "harness itself is broken and nothing below would mean anything"
    )

    before = await _drive_past_threshold(h)
    assert await _await_rotation(h.backend, before, STREAM_TIMEOUT), (
        "no rotation happened, so this test measured nothing"
    )

    h.send("echo MARKER_AFTER_ROT")
    assert await _await_text(h.seen, "MARKER_AFTER_ROT", STREAM_TIMEOUT), (
        "the terminal went SILENT after a rotation: the reader is no longer "
        "on the inode tmux is appending to"
    )


@pytest.mark.asyncio
async def test_rotation_reclaims_the_file_tmux_writes_to(harness, monkeypatch):
    monkeypatch.setattr(tmux_backend_module, "MAX_LOG_BYTES", SMALL_LOG_BYTES)
    h = harness

    before = await _drive_past_threshold(h)
    assert await _await_rotation(h.backend, before, STREAM_TIMEOUT), (
        "no rotation happened, so this test measured nothing"
    )

    h.send("echo MARKER_POST_ROTATION_ON_DISK")
    assert await _await_text(h.seen, "MARKER_POST_ROTATION_ON_DISK", STREAM_TIMEOUT)
    await asyncio.sleep(0.3)

    on_disk = h.pipe_path.read_bytes()
    assert b"MARKER_POST_ROTATION_ON_DISK" in on_disk, (
        "post-rotation output did not land at the managed pipe path. tmux is "
        "still writing to the inode the rotation renamed away, so the "
        "rotation reclaimed nothing and its size trigger now stats a decoy"
    )


@pytest.mark.asyncio
async def test_rotation_keeps_the_managed_file_bounded(harness, monkeypatch):
    monkeypatch.setattr(tmux_backend_module, "MAX_LOG_BYTES", SMALL_LOG_BYTES)
    h = harness

    for _ in range(3):
        before = await _drive_past_threshold(h)
        assert await _await_rotation(h.backend, before, STREAM_TIMEOUT), (
            "no rotation happened, so this test measured nothing"
        )

    h.send("echo MARKER_BOUNDED_TAIL")
    assert await _await_text(h.seen, "MARKER_BOUNDED_TAIL", STREAM_TIMEOUT)
    await asyncio.sleep(0.3)

    sizes = {p.name: p.stat().st_size for p in h.tmpdir.iterdir()}
    total = sum(sizes.values())
    assert total < SMALL_LOG_BYTES * 8, (
        f"the pipe files kept growing across rotations: {sizes}. A renamed "
        f"live file is still held open by tmux and still accumulating"
    )

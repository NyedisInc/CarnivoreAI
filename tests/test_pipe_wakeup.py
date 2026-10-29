
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.pipe_wakeup import KQUEUE_AVAILABLE, PipeWaiter

requires_kqueue = pytest.mark.skipif(
    not KQUEUE_AVAILABLE,
    reason="no select.kqueue on this platform; the waiter uses its sleep fallback",
)

ABSURD_TIMEOUT_SECONDS = 5.0

WAKE_BUDGET_SECONDS = 0.5


class _Appender:

    def __init__(self, path: Path) -> None:
        self._path = path
        self._proc = None

    def __enter__(self) -> "_Appender":
        self._proc = subprocess.Popen(
            ["sh", "-c", f"cat >> '{self._path}'"], stdin=subprocess.PIPE
        )
        self._wait_until_appending()
        return self

    def _wait_until_appending(self) -> None:
        marker = b"__appender_ready__\n"
        self.append(marker)
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                if self._path.stat().st_size >= len(marker):
                    return
            except FileNotFoundError:
                pass
            time.sleep(0.005)
        raise AssertionError(
            f"the `cat >>` appender never wrote to {self._path} - the "
            "fixture is broken, so nothing below would be measuring the "
            "watch"
        )

    def append(self, data: bytes) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def __exit__(self, *exc) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()


def _open_at_end(path: Path) -> int:
    fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
    os.lseek(fd, 0, os.SEEK_END)
    return fd


@requires_kqueue
@pytest.mark.asyncio
async def test_an_append_releases_the_wait_long_before_the_backstop(tmp_path):
    pipe = tmp_path / "pane.pipe"
    pipe.write_bytes(b"")
    with _Appender(pipe) as appender:
        fd = _open_at_end(pipe)
        waiter = PipeWaiter(fd)
        assert waiter.watching, (
            "kqueue is available but the watch did not register, so this "
            "test would be measuring the sleep fallback and proving nothing"
        )
        try:
            for attempt in range(5):
                loop = asyncio.get_running_loop()
                loop.call_later(0.05, appender.append, b"keystroke echo\n")
                t0 = time.perf_counter()
                woke = await waiter.wait(ABSURD_TIMEOUT_SECONDS)
                elapsed = time.perf_counter() - t0
                assert woke is True, (
                    f"attempt {attempt}: wait returned without an append "
                    "having released it"
                )
                assert elapsed < WAKE_BUDGET_SECONDS, (
                    f"attempt {attempt}: the append took {elapsed*1000:.1f} ms "
                    f"to release the wait, over the "
                    f"{WAKE_BUDGET_SECONDS*1000:.0f} ms budget. A "
                    f"{ABSURD_TIMEOUT_SECONDS}s backstop was in force, so "
                    "this cannot have been the timer."
                )
                assert os.read(fd, 8192), "woke, but no bytes were readable"
        finally:
            waiter.close()
            os.close(fd)


@requires_kqueue
@pytest.mark.asyncio
async def test_an_append_that_arrives_between_waits_is_not_slept_through(tmp_path):
    pipe = tmp_path / "pane.pipe"
    pipe.write_bytes(b"")
    with _Appender(pipe) as appender:
        fd = _open_at_end(pipe)
        waiter = PipeWaiter(fd)
        assert waiter.watching
        try:
            appender.append(b"arrived between waits\n")
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and not waiter._pending_data:
                await asyncio.sleep(0.005)
            assert waiter._pending_data, (
                "the append was never latched, so the race this test "
                "exists to close is still open"
            )
            t0 = time.perf_counter()
            woke = await waiter.wait(ABSURD_TIMEOUT_SECONDS)
            elapsed = time.perf_counter() - t0
            assert woke is True and elapsed < WAKE_BUDGET_SECONDS, (
                f"a wait that began with data already on disk took "
                f"{elapsed*1000:.1f} ms and returned {woke}. The append was "
                "notified before the wait started, so it has to be latched."
            )
            assert os.read(fd, 8192)
        finally:
            waiter.close()
            os.close(fd)


@pytest.mark.asyncio
async def test_a_quiet_file_still_returns_at_the_backstop(tmp_path):
    pipe = tmp_path / "quiet.pipe"
    pipe.write_bytes(b"")
    fd = _open_at_end(pipe)
    waiter = PipeWaiter(fd)
    try:
        t0 = time.perf_counter()
        woke = await waiter.wait(0.05)
        elapsed = time.perf_counter() - t0
        assert woke is False, "nothing was appended, so nothing may claim a wake"
        assert elapsed >= 0.04, (
            f"the wait returned after {elapsed*1000:.1f} ms without an "
            "append. A backstop that fires early is a busy loop."
        )
        assert elapsed < 2.0, (
            f"the backstop took {elapsed*1000:.1f} ms to fire; a missed "
            "notification would strand the terminal for that long"
        )
    finally:
        waiter.close()
        os.close(fd)


@pytest.mark.asyncio
async def test_the_fallback_behaves_exactly_like_the_old_sleep(tmp_path, monkeypatch):
    monkeypatch.setattr("src.core.pipe_wakeup.KQUEUE_AVAILABLE", False)
    pipe = tmp_path / "fallback.pipe"
    pipe.write_bytes(b"")
    with _Appender(pipe) as appender:
        fd = _open_at_end(pipe)
        waiter = PipeWaiter(fd)
        assert waiter.watching is False, (
            "KQUEUE_AVAILABLE was forced off, so no watch may be registered"
        )
        try:
            appender.append(b"ignored by the fallback\n")
            t0 = time.perf_counter()
            woke = await waiter.wait(0.05)
            elapsed = time.perf_counter() - t0
        finally:
            waiter.close()
            os.close(fd)
        assert woke is False
        assert elapsed >= 0.04, (
            f"the fallback returned after {elapsed*1000:.1f} ms; it must "
            "sleep the full interval exactly as the old loop did"
        )


@pytest.mark.asyncio
async def test_close_is_idempotent_and_survives_a_double_call(tmp_path):
    pipe = tmp_path / "close.pipe"
    pipe.write_bytes(b"")
    fd = _open_at_end(pipe)
    waiter = PipeWaiter(fd)
    try:
        waiter.close()
        waiter.close()
        assert waiter.watching is False
        assert await waiter.wait(0.01) is False
    finally:
        os.close(fd)


@pytest.mark.asyncio
async def test_a_watched_pipe_backs_off_to_a_long_idle_wait_and_the_fallback_keeps_the_poll(
    tmp_path, monkeypatch
):
    from src.core.pipe_wakeup import KQUEUE_AVAILABLE, WATCHED_BACKSTOP_SECONDS

    if not KQUEUE_AVAILABLE:
        pytest.skip("no kqueue on this platform")
    pipe = tmp_path / "watched.pipe"
    pipe.write_bytes(b"")
    with _Appender(pipe) as appender:
        fd = _open_at_end(pipe)
        waiter = PipeWaiter(fd)
        try:
            assert waiter.watching
            assert waiter.backstop(0.02) == WATCHED_BACKSTOP_SECONDS >= 0.5
            t0 = time.perf_counter()
            task = asyncio.ensure_future(waiter.wait(waiter.backstop(0.02)))
            await asyncio.sleep(0.2)
            assert not task.done(), "an idle watched wait must outlast the old 20 ms poll"
            appender.append(b"x")
            woke = await task
            elapsed = time.perf_counter() - t0
            assert woke is True
            assert elapsed < WATCHED_BACKSTOP_SECONDS, "the append, not the backstop, ended the wait"
        finally:
            waiter.close()
            os.close(fd)
    monkeypatch.setattr("src.core.pipe_wakeup.KQUEUE_AVAILABLE", False)
    fd = _open_at_end(pipe)
    fallback = PipeWaiter(fd)
    try:
        assert fallback.backstop(0.02) == 0.02
    finally:
        fallback.close()
        os.close(fd)

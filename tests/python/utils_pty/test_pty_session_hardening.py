
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from src.utils.pty_session import PTYBackend, PTYSession


async def _until(cond, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "condition never held"
        await asyncio.sleep(0.02)


def test_stop_ends_an_interactive_shell_promptly(tmp_path: Path) -> None:
    async def run() -> None:
        session = PTYSession("t", tmp_path)
        await session.start()
        await asyncio.sleep(0.3)
        started = time.monotonic()
        await asyncio.wait_for(session.stop(), timeout=8)
        assert time.monotonic() - started < 6

    asyncio.run(run())


def test_child_that_cannot_chdir_exits_127_and_never_returns_into_the_server(tmp_path: Path) -> None:
    async def run() -> None:
        out: list[bytes] = []
        session = PTYSession("t", tmp_path / "does-not-exist", on_output=out.append)
        await session.start(command="true")
        pid = session.pid
        assert pid
        _reaped, status = await asyncio.get_running_loop().run_in_executor(None, os.waitpid, pid, 0)
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 127
        await _until(lambda: b"failed to start" in b"".join(out))
        await session.stop()

    asyncio.run(run())


def test_env_reaches_the_child(tmp_path: Path) -> None:
    async def run() -> None:
        out: list[bytes] = []
        backend = PTYBackend("t", tmp_path, on_output=out.append)
        await backend.start(command="echo value=$M4_PTY_ENV", env={"M4_PTY_ENV": "carried"})
        await _until(lambda: b"value=carried" in b"".join(out))
        await backend.stop()

    asyncio.run(run())


def test_exited_child_is_not_alive(tmp_path: Path) -> None:
    async def run() -> None:
        session = PTYSession("t", tmp_path)
        await session.start(command="exit 0")
        await _until(lambda: not session.is_alive())
        await session.stop()

    asyncio.run(run())

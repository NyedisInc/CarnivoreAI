
from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path

import pytest

from src.core.pack.jobs import recipe


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize("how", ["cancel", "timeout"])
def test_no_grandchild_survives_a_cancel_or_a_timeout(tmp_path: Path, how: str) -> None:
    pidfile = tmp_path / "pid"
    step = recipe.Step(str(tmp_path), ["sh", "-c", f"sleep 300 & echo $! > {pidfile}; wait"], "k", "v")
    shell = "/bin/sh"

    async def main() -> None:
        task = asyncio.ensure_future(recipe.run([step], tmp_path / "log", shell=shell, timeout_s=1.0 if how == "timeout" else 60))
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            await asyncio.sleep(0.05)
        if how == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).ok is False

    asyncio.run(main())
    pid = int(pidfile.read_text())
    end = time.monotonic() + 3
    try:
        while _alive(pid) and time.monotonic() < end:
            time.sleep(0.05)
        assert not _alive(pid)
    finally:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)

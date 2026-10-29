
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.tmux_transport.run import (
    ERROR_NOT_STARTED,
    ERROR_TIMEOUT,
    TmuxRunResult,
    tmux_run,
    tmux_run_text,
)


def _fake_tmux(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "fake_tmux.py"
    script.write_text(body, encoding="utf-8")
    return [sys.executable, str(script)]


@pytest.mark.asyncio
async def test_run_returns_stdout_and_code(tmp_path: Path) -> None:
    prefix = _fake_tmux(tmp_path, "import sys; sys.stdout.write('-'.join(sys.argv[1:]))")
    done = await tmux_run("cloude", "a", "b", timeout=5.0, argv_prefix=prefix)
    assert (done.returncode, done.stdout, done.error, done.ok) == (0, b"a-b", None, True)


@pytest.mark.asyncio
async def test_run_keeps_stderr_only_when_asked(tmp_path: Path) -> None:
    prefix = _fake_tmux(tmp_path, "import sys; sys.stderr.write('boom'); sys.exit(3)")
    quiet = await tmux_run("cloude", "x", timeout=5.0, argv_prefix=prefix)
    loud = await tmux_run("cloude", "x", timeout=5.0, capture_stderr=True, argv_prefix=prefix)
    assert (quiet.returncode, quiet.stderr, quiet.ok) == (3, b"", False)
    assert loud.stderr == b"boom"


@pytest.mark.asyncio
async def test_a_hung_command_is_killed_and_reaped(tmp_path: Path) -> None:
    marker = tmp_path / "pid"
    prefix = _fake_tmux(tmp_path, f"import os,time; open({str(marker)!r},'w').write(str(os.getpid())); time.sleep(60)")
    started = time.monotonic()
    done = await tmux_run("cloude", "x", timeout=0.5, argv_prefix=prefix)
    assert done.error == ERROR_TIMEOUT and done.returncode is None
    assert time.monotonic() - started < 10
    pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_a_missing_binary_is_not_started_not_raised(tmp_path: Path) -> None:
    done = await tmux_run("cloude", "x", timeout=1.0, argv_prefix=[str(tmp_path / "nope")])
    assert done.error == ERROR_NOT_STARTED and done.returncode is None


def test_text_run_maps_the_runner_outcome() -> None:
    seen = {}

    def runner(argv, **kwargs):
        seen.update(kwargs, argv=argv)
        return SimpleNamespace(returncode=0, stdout="p\n", stderr=None)

    done = tmux_run_text("cloude", "list-panes", timeout=2.0, runner=runner, argv_prefix=["t", "-L", "cloude"])
    assert done == TmuxRunResult(0, "p\n", "", None)
    assert seen["argv"] == ["t", "-L", "cloude", "list-panes"] and seen["timeout"] == 2.0 and seen["text"] is True


def test_text_run_maps_timeout_and_oserror() -> None:
    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    def gone(argv, **kwargs):
        raise FileNotFoundError("tmux")

    assert tmux_run_text("c", "x", timeout=1, runner=slow, argv_prefix=["t"]).error == ERROR_TIMEOUT
    assert tmux_run_text("c", "x", timeout=1, runner=gone, argv_prefix=["t"]).error == ERROR_NOT_STARTED

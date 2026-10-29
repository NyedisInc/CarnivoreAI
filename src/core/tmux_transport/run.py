
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Generic, Optional, Sequence, TypeVar

import structlog

from src.core.tmux_discovery import tmux_argv_prefix

logger = structlog.get_logger()

ERROR_TIMEOUT = "timeout"
ERROR_NOT_STARTED = "not_started"

Output = TypeVar("Output", bytes, str)


@dataclass(frozen=True)
class TmuxRunResult(Generic[Output]):

    returncode: Optional[int]
    stdout: Output
    stderr: Output
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.returncode == 0


async def tmux_run(socket: str, *args: str, timeout: float, capture_stderr: bool = False,
                   argv_prefix: Optional[Sequence[str]] = None) -> TmuxRunResult[bytes]:
    argv = [*(argv_prefix if argv_prefix is not None else tmux_argv_prefix(socket)), *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE if capture_stderr else asyncio.subprocess.DEVNULL)
    except OSError as exc:
        logger.debug("tmux_run_not_started", verb=args[0] if args else "", error=type(exc).__name__)
        return TmuxRunResult(None, b"", b"", ERROR_NOT_STARTED)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        logger.debug("tmux_run_timeout", verb=args[0] if args else "", timeout=timeout)
        return TmuxRunResult(None, b"", b"", ERROR_TIMEOUT)
    return TmuxRunResult(proc.returncode, stdout or b"", stderr or b"")


def tmux_run_text(socket: str, *args: str, timeout: float,
                  runner: Callable[..., Any] = subprocess.run,
                  argv_prefix: Optional[Sequence[str]] = None) -> TmuxRunResult[str]:
    argv = [*(argv_prefix if argv_prefix is not None else tmux_argv_prefix(socket)), *args]
    try:
        done = runner(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return TmuxRunResult(None, "", "", ERROR_TIMEOUT)
    except OSError as exc:
        logger.debug("tmux_run_not_started", verb=args[0] if args else "", error=type(exc).__name__)
        return TmuxRunResult(None, "", "", ERROR_NOT_STARTED)
    return TmuxRunResult(done.returncode, done.stdout or "", done.stderr or "")

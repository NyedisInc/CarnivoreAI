
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Generic, Optional, Sequence, TypeVar

import structlog

from src.core.tmux_control.read_shape import Answer
from src.core.tmux_control.reader import control_run, control_run_async
from src.core.tmux_discovery import TmuxVersionSkewError, tmux_argv_prefix

logger = structlog.get_logger()

ERROR_TIMEOUT = "timeout"
ERROR_NOT_STARTED = "not_started"
ARGV_READ_TIMEOUT_SECONDS = 3.0

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


def _verb(args: Sequence[str]) -> str:
    return args[0] if args else ""


def _answered(answer: Answer, capture_stderr: bool = True) -> TmuxRunResult[bytes]:
    returncode, stdout, stderr = answer
    return TmuxRunResult(returncode, stdout, stderr if capture_stderr else b"")


def _as_text(raw: bytes) -> Optional[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _spawn_sync(argv: Sequence[str], verb: str, timeout: float, runner: Optional[Callable[..., Any]],
                text: bool) -> TmuxRunResult[Any]:
    empty: Any = "" if text else b""
    try:
        if runner is None:
            done = subprocess.run(list(argv), stdin=subprocess.DEVNULL, capture_output=True, text=text,
                                  timeout=timeout, check=False, close_fds=False)
        else:
            done = runner(list(argv), capture_output=True, text=text, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        logger.debug("tmux_run_timeout", verb=verb, timeout=timeout)
        return TmuxRunResult(None, empty, empty, ERROR_TIMEOUT)
    except (OSError, ValueError) as exc:
        logger.debug("tmux_run_not_started", verb=verb, error=type(exc).__name__)
        return TmuxRunResult(None, empty, empty, ERROR_NOT_STARTED)
    return TmuxRunResult(done.returncode, done.stdout or empty, done.stderr or empty)


async def tmux_run(socket: str, *args: str, timeout: float, capture_stderr: bool = False,
                   argv_prefix: Optional[Sequence[str]] = None) -> TmuxRunResult[bytes]:
    if argv_prefix is None:
        answer = await control_run_async(socket, args)
        if answer is not None:
            return _answered(answer, capture_stderr)
    argv = [*(argv_prefix if argv_prefix is not None else tmux_argv_prefix(socket)), *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE if capture_stderr else asyncio.subprocess.DEVNULL)
    except OSError as exc:
        logger.debug("tmux_run_not_started", verb=_verb(args), error=type(exc).__name__)
        return TmuxRunResult(None, b"", b"", ERROR_NOT_STARTED)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        logger.debug("tmux_run_timeout", verb=_verb(args), timeout=timeout)
        return TmuxRunResult(None, b"", b"", ERROR_TIMEOUT)
    return TmuxRunResult(proc.returncode, stdout or b"", stderr or b"")


def tmux_run_sync(socket: str, *args: str, timeout: float, runner: Optional[Callable[..., Any]] = None,
                  argv_prefix: Optional[Sequence[str]] = None) -> TmuxRunResult[bytes]:
    if runner is None and argv_prefix is None:
        answer = control_run(socket, args)
        if answer is not None:
            return _answered(answer)
    argv = [*(argv_prefix if argv_prefix is not None else tmux_argv_prefix(socket)), *args]
    return _spawn_sync(argv, _verb(args), timeout, runner, text=False)


def tmux_argv_stdout(argv: Sequence[str], timeout: float = ARGV_READ_TIMEOUT_SECONDS) -> Optional[str]:
    words = list(argv)
    if len(words) > 3 and words[1] == "-L":
        try:
            done = tmux_run_sync(words[2], *words[3:], timeout=timeout)
        except TmuxVersionSkewError:
            return None
    else:
        done = _spawn_sync(words, _verb(words[1:]), timeout, None, text=False)
    return done.stdout.decode("utf-8", errors="replace") if done.ok else None


def tmux_run_text(socket: str, *args: str, timeout: float,
                  runner: Optional[Callable[..., Any]] = None,
                  argv_prefix: Optional[Sequence[str]] = None) -> TmuxRunResult[str]:
    if runner is None and argv_prefix is None:
        answer = control_run(socket, args)
        stdout = _as_text(answer[1]) if answer is not None else None
        stderr = _as_text(answer[2]) if answer is not None else None
        if answer is not None and stdout is not None and stderr is not None:
            return TmuxRunResult(answer[0], stdout, stderr)
    argv = [*(argv_prefix if argv_prefix is not None else tmux_argv_prefix(socket)), *args]
    return _spawn_sync(argv, _verb(args), timeout, runner, text=True)

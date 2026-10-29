
from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path
from typing import Optional, Sequence

import structlog

from src.core.computers import join_helper, join_job, runtime
from src.core.desktop_app.payload_bytecode import bytecode_flags

log = structlog.get_logger(__name__)

COMMAND_NAME = "join-helper.command"
OPEN_BIN = "/usr/bin/open"
OPEN_TIMEOUT = 10.0
_ENTRY = "import sys; sys.path.insert(0, sys.argv[1]); from src.core.computers.join_helper import main; sys.exit(main(sys.argv[2:]))"
_opened_for: Optional[str] = None


def _quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def command_text(venv_python: str, server_dir: str, door_path: str, flags: Sequence[str] = ()) -> str:
    extra = "".join(f" {_quote(flag)}" for flag in flags)
    return (f"#!/bin/sh\nexec {_quote(venv_python)}{extra} -I -c {_quote(_ENTRY)} {_quote(server_dir)} --attach --door {_quote(door_path)}\n")


def write_command(directory: Path, text: str) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise OSError("fed directory is not private")
    tmp = directory / f".{COMMAND_NAME}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o700)
        target = directory / COMMAND_NAME
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return target


async def _open_terminal(path: Path) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            OPEN_BIN, "-g", "-a", "Terminal", str(path),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        return await asyncio.wait_for(proc.wait(), OPEN_TIMEOUT) == 0
    except (OSError, asyncio.TimeoutError) as exc:
        log.info("terminal_helper_open_failed", error_type=type(exc).__name__)
        return False


async def open_attach(job: join_job.JoinJob, *, created: bool) -> bool:
    global _opened_for
    if not created or job.state != "waiting_relay" or _opened_for == job.id:
        return False
    _opened_for = job.id
    server_dir = Path(__file__).resolve().parents[3]
    rt = runtime.active()
    try:
        if rt is None or rt.door is None:
            raise OSError("no door")
        text = command_text(sys.executable, str(server_dir), rt.door.path, bytecode_flags())
        path = await asyncio.to_thread(write_command, join_helper.fed_dir(), text)
        opened = await _open_terminal(path)
    except OSError as exc:
        log.info("terminal_helper_write_failed", error_type=type(exc).__name__)
        opened = False
    if not opened:
        join_job.end_waiting(job, "helper_not_started")
    log.info("terminal_helper_open", opened=opened)
    return opened

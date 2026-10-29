
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Optional

import structlog

from src.core.scrollback_replay import normalize_replay_newlines
from src.core.tmux_discovery import tmux_argv_prefix

logger = structlog.get_logger()

CAPTURE_CONCURRENCY = 6
CAPTURE_TIMEOUT_SECONDS = 3.0
_SIZE_FORMAT = "#{session_name}\t#{pane_width}\t#{pane_height}"


@dataclass(frozen=True)
class PaneScreen:

    status: str
    cols: int = 0
    rows: int = 0
    hash: str = ""
    screen: str = ""


def screen_hash(cols: int, rows: int, screen: str) -> str:
    return hashlib.sha1(f"{cols}x{rows}\n{screen}".encode("utf-8", "replace")).hexdigest()[:16]


def parse_capture(stdout: bytes, tmux_name: str) -> PaneScreen:
    head, _, body = stdout.partition(b"\n")
    parts = head.decode("utf-8", "replace").split("\t")
    if len(parts) != 3 or parts[0] != tmux_name or not (parts[1].isdigit() and parts[2].isdigit()):
        return PaneScreen("gone")
    cols, rows = int(parts[1]), int(parts[2])
    text = normalize_replay_newlines(body[:-1] if body.endswith(b"\n") else body).decode("utf-8", "replace")
    return PaneScreen("ok", cols, rows, screen_hash(cols, rows, text), text)


async def capture_screen(socket: str, tmux_name: str) -> PaneScreen:
    target = f"={tmux_name}:"
    argv = tmux_argv_prefix(socket) + [
        "display-message", "-p", "-t", target, _SIZE_FORMAT, ";",
        "capture-pane", "-p", "-e", "-t", target,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.debug("warroom_capture_failed", error=type(exc).__name__)
        return PaneScreen("gone")
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), CAPTURE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        logger.debug("warroom_capture_failed", error="TimeoutError")
        return PaneScreen("gone")
    return PaneScreen("gone") if proc.returncode != 0 else parse_capture(stdout, tmux_name)


async def capture_many(socket: str, names: dict[str, Optional[str]]) -> dict[str, PaneScreen]:
    gate = asyncio.Semaphore(CAPTURE_CONCURRENCY)

    async def one(name: Optional[str]) -> PaneScreen:
        if not name:
            return PaneScreen("gone")
        async with gate:
            return await capture_screen(socket, name)

    keys = list(names)
    results = await asyncio.gather(*(one(names[k]) for k in keys))
    return dict(zip(keys, results))


from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import structlog

from src.core.cross_session_search import strip_ansi
from src.core.stream_redactor import redact_whole
from src.core.tmux_transport.target import exact_pane_target

logger = structlog.get_logger()

MAX_LINES = 12
MAX_BYTES = 1024
CAPTURE_LINES = 60
TMUX_TIMEOUT_SECONDS = 3.0
TOTAL_TIMEOUT_SECONDS = 6.0
_TMUX_BANNER = re.compile(r"^Pane is dead \(.*\)$")


def tidy(raw: bytes) -> List[str]:
    text = redact_whole(strip_ansi(raw.decode("utf-8", errors="replace")).replace("\r", ""))
    lines = [ln.rstrip() for ln in text.split("\n") if not _TMUX_BANNER.match(ln.rstrip())]
    while lines and not lines[-1]:
        lines.pop()
    lines = lines[-MAX_LINES:]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and sum(len(ln.encode("utf-8")) + 1 for ln in lines) > MAX_BYTES:
        lines.pop(0)
    if lines and len(lines[-1].encode("utf-8")) >= MAX_BYTES:
        lines = [lines[-1].encode("utf-8")[: MAX_BYTES - 1].decode("utf-8", errors="ignore")]
    return lines


def read_dead_pane(socket: str, tmux_name: str) -> Dict[str, Any]:
    from src.core.tmux_backend import TmuxBackend  # noqa: PLC0415

    out: Dict[str, Any] = {}
    try:
        backend = TmuxBackend.for_external(session_name=tmux_name, working_dir=Path.home(), socket_name=socket)
        target = exact_pane_target(tmux_name)
        rc, shown, _ = backend._run_tmux_sync("display-message", "-p", "-t", target, "#{pane_dead} #{pane_dead_status}",
                                              check=False, timeout=TMUX_TIMEOUT_SECONDS, probe=True)
        dead, _, status = shown.decode("utf-8", errors="replace").strip().partition(" ")
        if rc != 0 or dead != "1":
            return out
        if status.isdigit() and int(status) < 256:
            out["exit"] = int(status)
        rc, raw, _ = backend._run_tmux_sync("capture-pane", "-p", "-J", "-S", f"-{CAPTURE_LINES}", "-t", target,
                                            check=False, timeout=TMUX_TIMEOUT_SECONDS, probe=True)
        tail = tidy(raw) if rc == 0 else []
        if tail:
            out["tail"] = tail
    except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as exc:
        logger.info("notify_died_capture_failed", error_type=type(exc).__name__)
    return out


async def capture(socket: str, tmux_name: str) -> Dict[str, Any]:
    if not socket or not tmux_name:
        return {}
    try:
        return await asyncio.wait_for(asyncio.to_thread(read_dead_pane, socket, tmux_name), TOTAL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.info("notify_died_capture_timeout")
        return {}

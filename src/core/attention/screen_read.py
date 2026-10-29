
from __future__ import annotations

import subprocess
import time
from typing import Callable, Hashable, Mapping, Optional

import structlog

from src.core.attention.screen_reuse import ScreenReuse
from src.core.tmux_control.reader import control_read

logger = structlog.get_logger()

CAPTURE_TIMEOUT_SECONDS = 2.0

_SHARED = ScreenReuse()


def shared_screens() -> ScreenReuse:
    return _SHARED


def capture_screen(socket: Optional[str], name: str, history: int = 0, row: Optional[int] = None) -> Optional[str]:
    from src.core.tmux_transport.target import exact_pane_target
    from src.core.tmux_discovery import tmux_argv_prefix

    if not socket:
        return None
    args = (["capture-pane", "-p", "-e", "-S", str(row), "-E", str(row)] if row is not None else
            ["capture-pane", "-p", "-S", str(-history) if history > 0 else "0"]) + ["-t", exact_pane_target(name)]
    kept = control_read(socket, args)
    if kept is not None:
        return kept.decode("utf-8", errors="replace")
    try:
        result = subprocess.run(
            tmux_argv_prefix(socket) + args,
            capture_output=True, timeout=CAPTURE_TIMEOUT_SECONDS, check=False,
            close_fds=False,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        logger.warning("attention_capture_failed", tmux_name=name, error=str(exc))
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def read_screen(screens: ScreenReuse, pane: Hashable, row: Mapping, capture: Callable[[], Optional[str]], *,
                force: bool = False, max_reuse_seconds: Optional[float] = None) -> Optional[str]:
    if not force:
        kept = screens.reusable(pane, row, time.time(), time.monotonic(), max_reuse_seconds=max_reuse_seconds)
        if kept is not None:
            return kept
    started_wall, started_mono = time.time(), time.monotonic()
    text = capture()
    screens.keep(pane, row, text, started_wall, started_mono)
    return text

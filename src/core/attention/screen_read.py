
from __future__ import annotations

import time
from typing import Callable, Hashable, Mapping, Optional

import structlog

from src.core.attention.screen_reuse import ScreenReuse
from src.core.tmux_transport.run import tmux_run_sync

logger = structlog.get_logger()

CAPTURE_TIMEOUT_SECONDS = 2.0

_SHARED = ScreenReuse()


def shared_screens() -> ScreenReuse:
    return _SHARED


def capture_screen(socket: Optional[str], name: str, history: int = 0, row: Optional[int] = None) -> Optional[str]:
    from src.core.tmux_transport.target import exact_pane_target

    if not socket:
        return None
    args = (["capture-pane", "-p", "-e", "-S", str(row), "-E", str(row)] if row is not None else
            ["capture-pane", "-p", "-S", str(-history) if history > 0 else "0"]) + ["-t", exact_pane_target(name)]
    result = tmux_run_sync(socket, *args, timeout=CAPTURE_TIMEOUT_SECONDS)
    if result.error:
        logger.warning("attention_capture_failed", tmux_name=name, error=result.error)
        return None
    return result.stdout.decode("utf-8", errors="replace") if result.returncode == 0 else None


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

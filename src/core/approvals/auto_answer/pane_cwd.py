
from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger()


async def read(socket: Optional[str], tmux_name: str) -> Optional[str]:
    if not socket or not tmux_name:
        return None
    from src.core.tmux_discovery import TmuxVersionSkewError  # noqa: PLC0415
    from src.core.tmux_session_cwd import CWD_PROBE_TIMEOUT_SECONDS
    from src.core.tmux_transport.run import tmux_run
    from src.core.tmux_transport.target import exact_pane_target

    try:
        done = await tmux_run(socket, "display-message", "-t", exact_pane_target(tmux_name), "-p", "#{pane_current_path}",
                              timeout=CWD_PROBE_TIMEOUT_SECONDS)
    except (TmuxVersionSkewError, OSError, ValueError) as exc:
        logger.debug("auto_answer_pane_cwd_failed", error=type(exc).__name__)
        return None
    text = done.stdout.decode("utf-8", errors="replace").strip() if done.ok else ""
    return text or None

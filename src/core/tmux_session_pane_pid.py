
from __future__ import annotations

from typing import Callable, Optional

import structlog

from src.core.tmux_session_cwd import CWD_PROBE_TIMEOUT_SECONDS, probe_session_format

logger = structlog.get_logger()

PANE_PID_FORMAT = "#{pane_pid}"


def probe_session_pane_pid(
    name: str, *, socket: str, timeout: float = CWD_PROBE_TIMEOUT_SECONDS
) -> Optional[int]:
    text = probe_session_format(name, socket=socket, fmt=PANE_PID_FORMAT, timeout=timeout)
    if text is None:
        return None
    try:
        pid = int(text)
    except ValueError:
        logger.warning("pane_pid_probe_not_a_number", tmux_name=name, tmux_socket=socket,
                       answer=text[:40])
        return None
    return pid if pid > 0 else None


def make_pane_pid_probe(socket: str) -> Callable[[str], Optional[int]]:
    return lambda name: probe_session_pane_pid(name, socket=socket)

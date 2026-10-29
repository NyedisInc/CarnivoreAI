
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import structlog

from src.core.tmux_transport.target import exact_pane_target

logger = structlog.get_logger()

PERSIST_PANE_DEAD = "pane_dead"

PANE_DEAD_TRUE = "1"

PANE_DEAD_FALSE = "0"


def probe_session_pane_dead(name: str, *, socket: str) -> Optional[bool]:
    if not name:
        return None
    from src.core.tmux_backend import LIST_TIMEOUT_SECONDS, TmuxBackend

    try:
        backend = TmuxBackend.for_external(
            session_name=name,
            working_dir=Path.home(),
            on_output=None,
            socket_name=socket,
        )
    except ValueError:
        logger.warning("pane_dead_probe_unsafe_name", tmux_name=name)
        return None
    try:
        rc, out, _err = backend._run_tmux_sync(
            "display-message",
            "-t",
            exact_pane_target(backend.tmux_session),
            "-p",
            "#{pane_dead}",
            check=False,
            timeout=LIST_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning(
            "pane_dead_probe_failed",
            tmux_name=name,
            tmux_socket=socket,
            error=str(exc),
        )
        return None
    if rc != 0:
        return None
    value = out.decode("utf-8", errors="replace").strip()
    if value == PANE_DEAD_TRUE:
        return True
    if value == PANE_DEAD_FALSE:
        return False
    return None


def make_pane_dead_probe(socket: str) -> Callable[[str], Optional[bool]]:
    return lambda name: probe_session_pane_dead(name, socket=socket)


def should_refuse_dead_husk(
    *,
    stored_row: Optional[Mapping[str, Any]],
    pane_dead: Optional[bool],
) -> bool:
    return not stored_row and pane_dead is True


def check_dead_husk(
    *,
    name: str,
    socket: str,
    epoch: int,
    stored_row: Optional[Mapping[str, Any]],
    pane_dead_probe: Optional[Callable[[str], Optional[bool]]],
) -> bool:
    if stored_row or pane_dead_probe is None:
        return False
    pane_dead = pane_dead_probe(name)
    if not should_refuse_dead_husk(stored_row=stored_row, pane_dead=pane_dead):
        return False
    logger.warning(
        "adopt_persist_refused_pane_dead",
        tmux_name=name,
        tmux_socket=socket,
        tmux_created_epoch=epoch,
        note=(
            "the pane was MEASURED dead and no row exists for this "
            "instance, so no row is minted for a husk"
        ),
    )
    return True


from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from src.core.tmux_control.client import get_control_input
from src.core.tmux_control.errors import (
    ControlFallback,
    ControlPaneGone,
    ControlStaleServer,
    ControlUnavailable,
    ControlWriteUnknown,
)
from src.core.tmux_control.names import control_input_enabled

if TYPE_CHECKING:
    from src.core.tmux_backend import TmuxBackend

logger = structlog.get_logger()


async def write(backend: "TmuxBackend", data: bytes) -> bytes:
    if backend.is_remote or not control_input_enabled():
        return data
    from src.core.tmux_backend import PaneDeadError

    client = get_control_input(backend.socket_name)
    try:
        for attempt in (1, 2):
            try:
                ref = await client.active_pane(backend.tmux_session)
                await client.send(ref.pane_id, ref.server_pid, data)
                return b""
            except ControlStaleServer:
                continue
            except ControlPaneGone as exc:
                if attempt == 2:
                    raise PaneDeadError(f"tmux pane of {backend.tmux_session!r} is gone") from exc
    except ControlUnavailable as exc:
        logger.debug("tmux_control_input_unavailable", reason=str(exc))
    except ControlFallback as fb:
        return fb.remaining
    except ControlWriteUnknown as exc:
        logger.warning("tmux_control_input_write_unknown", session=backend.tmux_session, reason=str(exc))
        raise
    return data

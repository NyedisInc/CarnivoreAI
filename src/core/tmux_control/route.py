
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
    """Deliver ``data`` through the control client when the switch is on.

    Description: returns the bytes still to send through today's subprocess path: all of them when
      the switch is off or the control path cannot take the write (nothing was sent), only the
      measured-unapplied tail after a mid-write failure, and ``b""`` when everything landed.
    Inputs: backend (TmuxBackend) - the writer; data (bytes) - keystrokes, at most the paste threshold.
    Output: bytes - what the caller must still write.
    Raises: PaneDeadError - tmux says the session or pane is gone, twice (no further retry).
      ControlWriteUnknown (a RuntimeError) - whether the keys landed could not be measured; the write is
      NOT retried (that could type them twice) and nothing stays queued for a later replay.
    Example: rest = await write(backend, b"ls\\r")  # b"" when the control client typed it
    """
    if not control_input_enabled():
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

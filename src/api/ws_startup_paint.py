
from __future__ import annotations

import asyncio
from typing import Optional, Protocol

import structlog

from src.core.hosts.identity import is_remote_backend


logger = structlog.get_logger()

_CLEAR_AND_HOME = b"\x1b[H\x1b[2J"

STALL_AFTER_SECONDS = 8.0

# nothing is ever written into the pane
_STALL_NOTICE = (
    b"\x1b[33m[carnivore] this session has been open for a while and has "
    b"printed nothing.\r\n"
    b"[carnivore] a shell startup script may be waiting on input you cannot "
    b"see.\r\n"
    b"[carnivore] press enter to release it, or check your shell rc for a "
    b"prompt.\x1b[0m\r\n"
)


class _PaintTarget(Protocol):

    async def send_bytes(self, data: bytes) -> None: ...


class _PaintBackend(Protocol):

    def pane_in_alternate_screen(self) -> bool: ...

    def capture_visible_screen(self) -> bytes: ...

    def session_age_seconds(self) -> Optional[float]: ...


def _looks_stalled(backend: _PaintBackend) -> bool:
    probe = getattr(backend, "session_age_seconds", None)
    if probe is None:
        return False
    try:
        age = probe()
    except Exception as exc:
        logger.warning("ws_paint_age_probe_failed", error=str(exc))
        return False
    if age is None:
        logger.debug("ws_paint_age_unknown")
        return False
    return age >= STALL_AFTER_SECONDS


async def paint_on_attach(
    websocket: _PaintTarget,
    backend: Optional[_PaintBackend],
) -> str:
    """Make the pane's current screen visible to a freshly attached client.

    Nothing is ever written into the pane. See the module docstring.

    Args:
        websocket: Connected client socket. Receives one binary frame
            carrying the captured screen, or the stall notice, or nothing.
        backend: The session's backend, or None when it could not be
            resolved (in which case there is nothing to do).

    Returns:
        The strategy used, for logging and tests: ``"screen"`` (capture
        sent to the client), ``"stalled"`` (screen was blank, the pane is
        not a full-screen app, and the session is old enough that
        blankness is itself the finding, so a notice was sent), or
        ``"none"`` (no backend, or nothing to paint and no reason to
        think anything is wrong).

    Example:
        >>> await paint_on_attach(ws, backend)
        'screen'
    """
    if backend is None:
        return "none"

    remote = is_remote_backend(backend)
    if remote:
        try:
            await backend.ensure_streaming()
        except OSError as exc:
            logger.warning("ws_paint_remote_stream_failed", error=str(exc))

    try:
        alternate = await asyncio.to_thread(backend.pane_in_alternate_screen)
    except Exception as exc:
        logger.warning("ws_paint_alt_probe_failed", error=str(exc))
        alternate = True

    try:
        screen = await asyncio.to_thread(backend.capture_visible_screen)
    except Exception as exc:
        logger.warning("ws_paint_capture_failed", error=str(exc))
        return "none"

    if not screen:
        if not alternate and await asyncio.to_thread(_looks_stalled, backend):
            try:
                await websocket.send_bytes(_CLEAR_AND_HOME + _STALL_NOTICE)
            except Exception as exc:
                logger.warning("ws_paint_stall_send_failed", error=str(exc))
                return "none"
            logger.info("ws_paint_stall_announced")
            return "stalled"
        return "none"

    try:
        await websocket.send_bytes(_CLEAR_AND_HOME + screen)
    except Exception as exc:
        logger.warning("ws_paint_screen_send_failed", error=str(exc))
        return "none"

    logger.debug("ws_paint_screen_sent", size=len(screen))
    return "screen"

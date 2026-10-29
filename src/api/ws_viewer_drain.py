
from __future__ import annotations

import asyncio
import base64

import structlog
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from uvicorn.protocols.utils import ClientDisconnected

from src.api.ws_repaint import capture_screen
from src.api.ws_startup_paint import _CLEAR_AND_HOME
from src.core import viewer_fanout
from src.core.bounded_stream import REASON_OVERFLOW
from src.core.bounded_stream import BoundedStream
from src.core.perf_hooks.monitor import PERF, frame_topic

logger = structlog.get_logger()

# the socket closed
_CLOSED_SOCKET_MARKERS = ("once a close message has been sent", "after sending 'websocket.close'")


def _client_gone(exc: BaseException, stream: BoundedStream) -> bool:
    if isinstance(exc, (WebSocketDisconnect, ClientDisconnected)):
        return True
    if isinstance(exc, RuntimeError) and any(m in str(exc) for m in _CLOSED_SOCKET_MARKERS):
        return True
    return stream.closed


async def _pump_text(queue: asyncio.Queue, stream: BoundedStream) -> None:
    """Move text messages from a source queue into a viewer's outbox.

    Description: A FEEDER, NOT A WRITER. It never touches the socket, so
      adding a source of server-to-client messages cannot add a second
      coroutine sending on it. The log monitor and the local-server
      tracker each hand out their own unbounded fan-out queue; this is
      where their output enters this viewer's bound and starts counting
      against the same budget as its terminal bytes. Returns when the
      viewer's stream is finished, which is the teardown signal.
    Inputs: queue (asyncio.Queue) - the source's own subscription;
      stream (BoundedStream) - this viewer's outbox.
    Output: None.
    Example: asyncio.create_task(_pump_text(log_queue, viewer_stream))
    """
    try:
        while True:
            message = await queue.get()
            if stream.closed:
                return
            viewer_fanout.offer_text(stream, message)
    except asyncio.CancelledError:
        pass


async def _drain_viewer(
    websocket: WebSocket,
    stream: BoundedStream,
    log_monitor=None,
    session_id=None,
) -> None:
    try:
        while True:
            frame = await stream.get()
            if frame is None:
                return
            if frame.kind == viewer_fanout.FRAME_TEXT:
                await websocket.send_text(frame.payload)
                if PERF.enabled:
                    PERF.record_ws("terminal_out", frame_topic(frame.payload),
                                   len(frame.payload), stream.label)
                continue

            if frame.kind == viewer_fanout.FRAME_RESYNC:
                screen, _why = await capture_screen(websocket, session_id)
                if screen is None:
                    stream.close(REASON_OVERFLOW)
                    continue
                await websocket.send_text(frame.payload)
                await websocket.send_bytes(_CLEAR_AND_HOME + screen)
                if PERF.enabled:
                    PERF.record_ws("terminal_out", frame.kind, len(screen), stream.label)
                continue

            raw_bytes = base64.b64decode(frame.payload)
            if PERF.enabled:
                PERF.record_ws("terminal_out", frame.kind, len(raw_bytes), stream.label)
            if frame.kind == viewer_fanout.FRAME_PAINT:
                await websocket.send_bytes(raw_bytes)
                continue

            _services = getattr(websocket.app.state, "services", None)
            _registry = getattr(_services, "registry", None)
            _backend = None
            if _registry is not None:
                if session_id:
                    _backend = _registry.get_backend(session_id)
                else:
                    _backend = _registry.current_backend()
            in_replay = (
                _backend is not None
                and getattr(_backend, "replay_in_progress", False)
            )
            if log_monitor and not in_replay:
                try:
                    text = raw_bytes.decode("utf-8", errors="replace")
                    log_monitor._detect_patterns(text)
                except Exception as e:
                    logger.debug("pattern_detection_error", error=str(e))

            await websocket.send_bytes(raw_bytes)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        if _client_gone(e, stream):
            logger.debug("drain_viewer_client_gone", error_type=type(e).__name__,
                         stream=stream.label)
        else:
            logger.error("drain_viewer_error", error=str(e), error_type=type(e).__name__)
    finally:
        stream.close()

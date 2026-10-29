
from __future__ import annotations

import asyncio
import json
import time
from contextlib import closing, suppress

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from src.api import terminal_socket_role as socket_role
from src.api import ws_credential
from src.core.browsers import store
from src.core.browsers.input import InputRejected
from src.core.browsers.manager import BrowserUnavailable, CapReached
from src.core.browsers.stream import OVERFLOW_CLOSE_CODE, Viewer
from src.core.browsers.url_policy import UrlRefused
from src.core.db import connect, db_path_for

logger = structlog.get_logger()

router = APIRouter()

MAX_MESSAGE_CHARS = 256 * 1024

MAX_MESSAGES_PER_SECOND = 400

# could not
LAUNCH_REFUSED_CLOSE_CODE = 4503

UNKNOWN_CLOSE_CODE = 4404


def _read_row(state_dir, browser_id: str):
    with closing(connect(db_path_for(state_dir), create=False)) as conn:
        return store.get(conn, browser_id)


@router.websocket("/ws/browser")
async def browser_socket(websocket: WebSocket) -> None:
    """Stream one browser session's screen and forward a viewer's input."""
    if not await ws_credential.handshake(websocket):
        return
    manager = websocket.app.state.browser_manager
    browser_id = websocket.query_params.get("browser_id", "")
    row = None
    if store.is_valid_id(browser_id):
        try:
            row = await run_in_threadpool(_read_row, manager.state_dir, browser_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("browser_socket_row_unreadable", error=type(exc).__name__)
            await websocket.close(code=1011, reason="datastore unreadable")
            return
    if row is None:
        logger.warning("browser_socket_unknown_id")
        await websocket.close(code=UNKNOWN_CLOSE_CODE, reason="unknown browser session")
        return
    role = socket_role.role_for_query(websocket.query_params)
    try:
        live, relaunched = await manager.ensure_live(browser_id, row.last_url)
    except (CapReached, BrowserUnavailable) as exc:
        code = "cap_reached" if isinstance(exc, CapReached) else "browser_unavailable"
        await websocket.send_text(json.dumps({"type": "error", "code": code, "message": str(exc)}))
        await websocket.close(code=LAUNCH_REFUSED_CLOSE_CODE, reason=code)
        return

    viewer = Viewer(websocket)
    if relaunched:
        viewer.offer_text({"type": "restarted"})
    writer = asyncio.create_task(viewer.run())
    try:
        if not await manager.join(live, viewer):
            viewer.close(OVERFLOW_CLOSE_CODE, "too many viewers")
            return
        await _read_loop(websocket, live, viewer, role)
    finally:
        await manager.leave(live, viewer)
        viewer.close()
        with suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(writer, 2.0)


async def _read_loop(websocket: WebSocket, live, viewer: Viewer, role) -> None:
    window_start, count = time.monotonic(), 0
    while True:
        try:
            message = await websocket.receive()
        except (WebSocketDisconnect, RuntimeError):
            return
        if message["type"] == "websocket.disconnect":
            return
        now = time.monotonic()
        if now - window_start >= 1.0:
            window_start, count = now, 0
        count += 1
        text = message.get("text")
        if count > MAX_MESSAGES_PER_SECOND or (text is not None and len(text) > MAX_MESSAGE_CHARS):
            viewer.close(OVERFLOW_CLOSE_CODE, "input bound exceeded")
            return
        if text is None:
            viewer.close(1003, "binary messages are not accepted")
            return
        try:
            msg = json.loads(text)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        kind = msg.get("type")
        if not role.accepts_input:
            logger.info(socket_role.OBSERVER_REFUSAL_EVENT, reason=str(kind)[:16], socket="browser")
            continue
        try:
            await live.handle(msg, may_resize=role.negotiates_size)
        except UrlRefused as exc:
            viewer.offer_text({"type": "notice", "message": str(exc)})
        except InputRejected as exc:
            logger.info("browser_input_rejected", type=str(kind)[:16], reason=str(exc))
        except Exception as exc:  # noqa: BLE001
            if live.stopping:
                return
            logger.info("browser_command_failed", type=str(kind)[:16], error=type(exc).__name__)

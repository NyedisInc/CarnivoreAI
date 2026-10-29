
import asyncio
import json
import sqlite3

from fastapi import WebSocket, WebSocketDisconnect
import structlog

from src.models import (
    WSMessageType,
    WSPTYResizeMessage,
    WSErrorMessage,
)
from src.api.ws_connections import connection_manager
from src.api.resize_negotiation import apply_negotiated_resize
from src.api import ws_repaint
from src.api import terminal_socket_role as socket_role
from src.core import db, viewer_fanout
from src.core.perf_hooks.monitor import PERF
from src.api.ws_input_pipeline import InputPipeline

logger = structlog.get_logger()


async def _peer_swarm_body(websocket: WebSocket, session_manager, session_id) -> "int | None":
    if (getattr(websocket, 'scope', None) or {}).get('peer_grant') is None:
        return None
    from src.core.swarm import delivery
    info = await session_manager.get_session_info(session_id=session_id)
    row_id = getattr(info, 'session_row_id', None)
    try:
        return row_id if await asyncio.to_thread(delivery.is_swarm_body, row_id) else None
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError):
        return row_id


async def _record_peer_keys(row_id: int, session_id) -> bool:
    from src.core.swarm import delivery
    try:
        await asyncio.to_thread(delivery.record_for_session_row, row_id, 'send_keys', f'peer_keys:{session_id}')
        return True
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError) as exc:
        logger.warning('peer_keys_record_failed', session_id=session_id, error_type=type(exc).__name__)
        return False


async def receive_messages(
    websocket: WebSocket, session_manager, session_id=None, stream=None,
    role: socket_role.TerminalSocketRole = socket_role.PRIMARY_ROLE,
):
    """
    Receive messages from the WebSocket client.

    IT READS AND IT DOES NOT SEND. Its two replies - the pong and the
    input-failure error - are OFFERED into the viewer's outbox so the
    writer task delivers them, because a send from here would be a second
    coroutine on this socket and two of those interleave frames into a
    stream nothing reports as broken. With no stream (an older caller, a
    test double) those replies are skipped rather than sent directly: a
    dropped pong costs a keepalive, and a silent second writer costs a
    corrupted terminal.

    Args:
        websocket: WebSocket connection
        session_manager: SessionManager instance
        session_id: the session this WS is bound to (None = current)
        stream: this viewer's outbox (BoundedStream), or None
        role: what this socket may do. ``accepts_input`` False drops
            binary frames and resizes with a logged refusal and keeps
            reading. Defaults to the primary role, so an older caller
            behaves exactly as it always did.
    """
    swarm_row_id = await _peer_swarm_body(websocket, session_manager, session_id)

    def report_input_failure(exc: Exception, length: int) -> None:
        logger.error(
            "input_failed",
            error=(exc.reason if isinstance(exc, UnicodeDecodeError) else str(exc)),
            length=length,
        )
        if viewer_fanout.is_viewer_stream(stream):
            viewer_fanout.offer_text(
                stream,
                WSErrorMessage(error="input_failed", message=str(exc)).model_dump_json(),
            )

    async def deliver_input(text: str) -> None:
        await session_manager.send_input(text, session_id=session_id)
        if websocket.scope.get('peer_grant') is None and text:
            from src.core.crosstalk.contacts import schedule_owner_input
            schedule_owner_input(websocket.app, session_id)

    pipeline = InputPipeline(deliver_input, report_input_failure)
    try:
        while True:
            try:
                message = await websocket.receive()

                if "bytes" in message:
                    data = message["bytes"]
                    if not role.accepts_input:
                        socket_role.refuse_frame(
                            session_id, socket_role.REASON_BINARY_INPUT)
                        continue
                    logger.debug("pty_input_received", data_len=len(data))
                    if PERF.enabled:
                        PERF.record_ws("terminal_in", "pty_input", len(data), str(session_id))
                    if swarm_row_id is not None and not await _record_peer_keys(swarm_row_id, session_id):
                        continue
                    try:
                        await pipeline.submit(data.decode('utf-8'))
                    except UnicodeDecodeError as e:
                        report_input_failure(e, len(data))

                elif "text" in message:
                    data = message["text"]
                    try:
                        msg = json.loads(data)
                        msg_type = msg.get("type")

                        if (msg_type == WSMessageType.PTY_RESIZE
                                and not role.negotiates_size):
                            socket_role.refuse_frame(
                                session_id, socket_role.REASON_PTY_RESIZE)
                        elif msg_type == WSMessageType.PTY_RESIZE:
                            resize_msg = WSPTYResizeMessage(**msg)
                            logger.info("terminal_resize_request", cols=resize_msg.cols, rows=resize_msg.rows, hidden=resize_msg.hidden)
                            try:
                                await apply_negotiated_resize(
                                    session_manager, session_id, websocket,
                                    resize_msg.cols, resize_msg.rows,
                                    connection_manager,
                                    hidden=resize_msg.hidden,
                                )
                            except Exception as e:
                                logger.error("resize_failed", error=str(e))

                        elif msg_type == WSMessageType.REPAINT:
                            await ws_repaint.repaint(websocket, session_id, stream)

                        elif msg_type == WSMessageType.PING:
                            if viewer_fanout.is_viewer_stream(stream):
                                viewer_fanout.offer_text(
                                    stream, json.dumps({"type": WSMessageType.PONG})
                                )

                    except json.JSONDecodeError:
                        logger.warning("invalid_json_received", length=len(data))
                    except Exception as e:
                        logger.error("message_processing_error", error=str(e))

            except RuntimeError as e:
                if "Cannot call \"receive\" once a disconnect message has been received" in str(e):
                    logger.debug("websocket_already_disconnected", error=str(e))
                    break
                else:
                    logger.error("receive_error", error=str(e))
                    raise
            except Exception as e:
                logger.error("receive_error", error=str(e))
                raise

    except WebSocketDisconnect:
        raise
    except Exception as e:
        logger.error("receive_messages_error", error=str(e))
        raise
    finally:
        await pipeline.close()

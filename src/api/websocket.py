

import asyncio
import json
import base64
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from typing import Optional, Set
import structlog

from src.models import (
    WSMessageType,
    WSPTYDataMessage,
    WSPTYInputMessage,
    WSTerminalReadyMessage
)
from src.api.attach_settle import (
    NO_RESIZE_ATTEMPTED,
    ResizeOutcome,
    SettleVerdict,
    decide_settle,
    read_pane_geometry,
    settle_if_needed,
)
from src.api import peer_ws_auth, ws_credential
from src.core.federation import peer_terminal_proxy
from src.api.ws_connections import ConnectionManager, connection_manager, _resolve_backend
from src.api.ws_viewer_drain import _drain_viewer, _pump_text
from src.api.resize_negotiation import apply_negotiated_resize
from src.api import size_master
from src.api.ws_startup_paint import paint_on_attach
from src.api.ws_receive import receive_messages
from src.api import terminal_socket_role as socket_role
from src.core import viewer_fanout
from src.core.bounded_stream import OFFER_ACCEPTED, BoundedStream

logger = structlog.get_logger()

router = APIRouter()

@router.websocket("/ws/terminal", dependencies=[Depends(peer_ws_auth.peer_ws_marker)])
async def websocket_terminal(websocket: WebSocket):
    """
    WebSocket endpoint for real-time PTY terminal streaming.

    Provides bidirectional communication:
    - Server -> Client: PTY output data (base64 encoded)
    - Client -> Server: User input, resize events

    Args:
        websocket: WebSocket connection

    Auth protocol:
        Client opens WS with subprotocols=["cloude.jwt.v1", <jwt_token>].
        Server validates the JWT, accepts the handshake echoing the marker
        as the negotiated subprotocol. Failures close with:
          - 4401 on missing marker / missing token / invalid token
          - 4400 on malformed Sec-WebSocket-Protocol header
    """
    if not await ws_credential.handshake(websocket, allow_peer=True):
        return

    session_manager = websocket.app.state.session_manager
    registry = websocket.app.state.services.registry
    local_servers = websocket.app.state.local_servers
    log_monitor = websocket.app.state.log_monitor

    role = socket_role.role_for_query(websocket.query_params)

    requested_sid = websocket.query_params.get("session_id")
    if await peer_terminal_proxy.dispatch(websocket, registry, requested_sid):
        return
    if websocket.scope.get("peer_grant") is not None:
        requested_sid = peer_ws_auth.local_session_id(registry, requested_sid)
    target_sid: Optional[str] = None
    if requested_sid:
        if requested_sid not in registry.sessions:
            logger.warning("ws_unknown_session", session_id=requested_sid)
            await websocket.close(code=4404, reason="unknown session")
            return
        target_sid = requested_sid
    else:
        cur = registry.current_session()
        target_sid = cur.id if cur is not None else None

    viewer_stream = registry.subscribe(target_sid, resync=True)

    await connection_manager.connect(websocket, viewer_stream)
    connection_manager.bind_session(websocket, target_sid)
    if role.marks_viewed and target_sid and hasattr(
            session_manager, "mark_session_viewed"):
        try:
            session_manager.mark_session_viewed(target_sid)
        except Exception as exc:
            logger.warning(
                "mark_session_viewed_failed", session_id=target_sid, error=str(exc)
            )

    local_servers_queue = local_servers.subscribe()

    log_queue = log_monitor.subscribe()

    try:
        handshake_cols: Optional[int] = None
        handshake_rows: Optional[int] = None
        handshake_hidden = False
        if role.awaits_handshake:
            await websocket.send_text(json.dumps({
                "type": WSMessageType.REQUEST_DIMS,
            }))
            logger.debug("ws_request_dims_sent")
            if role.negotiates_size:
                await size_master.attach(websocket, session_manager, target_sid)

            handshake_deadline_s = 2.0
            handshake_start = asyncio.get_event_loop().time()
            while True:
                remaining = handshake_deadline_s - (
                    asyncio.get_event_loop().time() - handshake_start
                )
                if remaining <= 0:
                    logger.warning("ws_handshake_timeout")
                    break
                try:
                    raw = await asyncio.wait_for(
                        websocket.receive(),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    logger.warning("ws_handshake_timeout")
                    break

                if "text" in raw and raw["text"]:
                    try:
                        msg = json.loads(raw["text"])
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == WSMessageType.PTY_RESIZE:
                        try:
                            handshake_cols = int(msg["cols"])
                            handshake_rows = int(msg["rows"])
                            handshake_hidden = msg.get("hidden") is True
                        except (KeyError, ValueError, TypeError):
                            logger.warning("ws_handshake_bad_dims", msg=msg)
                        break
                    continue

        if handshake_cols and handshake_rows:
            logger.info(
                "ws_handshake_resize",
                cols=handshake_cols,
                rows=handshake_rows,
                hidden=handshake_hidden,
            )
            measured = await read_pane_geometry(
                _resolve_backend(registry, target_sid)
            )
            try:
                outcome = await apply_negotiated_resize(
                    session_manager, target_sid, websocket,
                    handshake_cols, handshake_rows, connection_manager,
                    known_pane_size=measured, hidden=handshake_hidden,
                )
            except Exception as exc:
                logger.error("ws_handshake_resize_failed", error=str(exc))
                outcome = ResizeOutcome(
                    target=(handshake_cols, handshake_rows),
                    issued=True,
                    failed=True,
                )

            verdict = decide_settle(measured, outcome)
            await settle_if_needed(verdict)
            logger.debug(
                "ws_handshake_settle",
                settled=verdict.settle,
                reason=verdict.reason,
            )

            _strategy = await paint_on_attach(
                websocket, _resolve_backend(registry, target_sid))
            logger.debug("ws_handshake_painted", strategy=_strategy)
        else:
            verdict = (
                decide_settle(None, NO_RESIZE_ATTEMPTED)
                if role.awaits_handshake
                else SettleVerdict(False, "observer_no_resize")
            )
            await settle_if_needed(verdict)
            if not role.awaits_handshake:
                observed = await read_pane_geometry(
                    _resolve_backend(registry, target_sid)
                )
                if observed:
                    try:
                        await websocket.send_text(json.dumps({
                            "type": WSMessageType.TERMINAL_SIZE,
                            "cols": observed[0],
                            "rows": observed[1],
                        }))
                        logger.debug(
                            "ws_observer_size_sent",
                            cols=observed[0],
                            rows=observed[1],
                        )
                    except (WebSocketDisconnect, RuntimeError) as exc:
                        logger.info("ws_observer_size_not_delivered", error=str(exc))
                else:
                    logger.info("ws_observer_size_unreadable")
            _strategy = await paint_on_attach(
                websocket, _resolve_backend(registry, target_sid))
            logger.info("ws_handshake_painted_fallback", strategy=_strategy)

        login_outcome = "none"
        is_primary = role.accepts_input
        if is_primary and target_sid and hasattr(session_manager, "flush_pending_login"):
            try:
                login_outcome = await session_manager.flush_pending_login(target_sid)
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                logger.warning("ws_pending_login_failed", error=str(exc))
                login_outcome = "unknown"

        startup_command = "unknown"
        if login_outcome != "none":
            startup_command = login_outcome
        elif not is_primary:
            startup_command = "unknown"
        elif not target_sid:
            startup_command = "unknown"
        else:
            startup_command = "none"

        try:
            await websocket.send_text(json.dumps(
                WSTerminalReadyMessage(startup_command=startup_command).model_dump()
            ))
            logger.debug("ws_terminal_ready_sent", startup_command=startup_command)
        except (WebSocketDisconnect, RuntimeError) as exc:
            logger.info("ws_terminal_ready_not_delivered", error=str(exc))
    except WebSocketDisconnect:
        logger.info("ws_handshake_client_disconnected")
        registry.unsubscribe(viewer_stream, target_sid)
        local_servers.unsubscribe(local_servers_queue)
        log_monitor.unsubscribe(log_queue)
        if role.negotiates_size:
            await size_master.release_client(
                session_manager, target_sid, websocket, connection_manager)
        connection_manager.disconnect(websocket)
        return
    except Exception as exc:
        logger.error("ws_handshake_error", error=str(exc))

    try:
        writer_task = asyncio.create_task(_drain_viewer(
            websocket, viewer_stream, log_monitor, target_sid))
        receive_task = asyncio.create_task(
            receive_messages(
                websocket, session_manager, target_sid, viewer_stream, role=role)
        )
        pump_local_servers_task = asyncio.create_task(
            _pump_text(local_servers_queue, viewer_stream)
        )
        pump_logs_task = asyncio.create_task(
            _pump_text(log_queue, viewer_stream)
        )

        done, pending = await asyncio.wait(
            [receive_task, writer_task, pump_local_servers_task, pump_logs_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        overflowed = viewer_stream.overflowed

        for task in pending:
            task.cancel()

        if overflowed:
            logger.warning(
                "viewer_disconnected_queue_overflow",
                session_id=target_sid,
                close_code=viewer_fanout.VIEWER_OVERFLOW_CLOSE_CODE,
                max_chunks=viewer_fanout.MAX_VIEWER_QUEUE_CHUNKS,
                max_bytes=viewer_fanout.MAX_VIEWER_QUEUE_BYTES,
            )
            try:
                await websocket.close(
                    code=viewer_fanout.VIEWER_OVERFLOW_CLOSE_CODE,
                    reason="viewer queue overflow",
                )
            except RuntimeError:
                pass

    except WebSocketDisconnect:
        logger.info("websocket_client_disconnected")
    except Exception as e:
        logger.error("websocket_error", error=str(e))
    finally:
        registry.unsubscribe(viewer_stream, target_sid)
        local_servers.unsubscribe(local_servers_queue)
        log_monitor.unsubscribe(log_queue)
        if role.negotiates_size:
            await size_master.release_client(
                session_manager, target_sid, websocket, connection_manager)
        connection_manager.disconnect(websocket)


from __future__ import annotations

import asyncio
import json
import re
import socket
import uuid
from pathlib import Path
from typing import Any

import structlog

from src.core.attention.registry_record import REG_ABSENT, REG_STALE
from src.core.attention.registry_index import registry_for_session
from src.core.conversation_writers import MeasureError, read_pid_record, read_process_table, same_process_start
from src.core.session_transcript_presence import conversation_presence
from src.core.crosstalk.delivery.identity import conversation_id

logger = structlog.get_logger(__name__)
_NAME = re.compile(r"^[^\"<>\r\n]{1,100}$")
_CLOSE = "</cross-session-message>"


def _receipt(path: Path, msg_id: str, message: dict | None = None, conversation: str | None = None) -> bool:
    expected = body = None
    name = str(message.get("sender_name") or "carnivore") if isinstance(message, dict) else ""
    if message is not None and conversation and _NAME.fullmatch(name):
        try:
            from src.core.crosstalk.delivery.dispatcher import envelope

            body = envelope(message)
            expected = native_frame(message, msg_id, name)["message"]["content"]
        except (KeyError, TypeError):
            pass
    enqueued = False
    absorbed: set[tuple[str, str]] = set()
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 1024 * 1024))
            if stream.tell():
                stream.readline()
            for line in stream:
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                origin = row.get("origin") if isinstance(row, dict) else None
                if isinstance(origin, dict) and origin.get("kind") == "peer" and origin.get("msg_id") == msg_id:
                    return True
                if expected is None or not isinstance(row, dict) or row.get("sessionId") != conversation:
                    continue
                if enqueued and row.get("type") == "user" and row.get("turnOrigin") == "peer":
                    peer = row.get("origin")
                    content = row.get("message")
                    if (row.get("promptSource") == "system" and row.get("queueSkipAttachments") is True
                            and isinstance(peer, dict) and peer.get("kind") == "peer"
                            and peer.get("from") == "unknown" and peer.get("fromMode") == "bypass"
                            and peer.get("name") == name and peer.get("body") == body
                            and isinstance(content, dict) and content.get("role") == "user"
                            and isinstance(content.get("content"), str)
                            and content["content"].startswith("Another Claude session sent a message:\n" + expected)
                            and content["content"].count(expected) == 1):
                        return True
                if row.get("type") == "queue-operation" and row.get("content") == expected:
                    if row.get("operation") == "enqueue":
                        enqueued = True
                    elif enqueued and row.get("operation") == "remove" and row.get("reason") == "absorbed_mid_turn":
                        delivery_id, command_uuid = row.get("deliveryId"), row.get("commandUuid")
                        if isinstance(delivery_id, str) and delivery_id and isinstance(command_uuid, str) and command_uuid:
                            absorbed.add((delivery_id, command_uuid))
                if row.get("type") == "attachment":
                    attachment = row.get("attachment")
                    if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
                        continue
                    peer = attachment.get("origin")
                    if (attachment.get("prompt") == expected
                            and (attachment.get("delivery_id"), attachment.get("source_uuid")) in absorbed
                            and isinstance(peer, dict) and peer.get("kind") == "peer"
                            and peer.get("from") == "unknown" and peer.get("fromMode") == "bypass"
                            and peer.get("name") == name and peer.get("body") == body):
                        return True
    except OSError:
        return False
    return False


def _post(path: str, frame: dict) -> bool:
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(5)
        try:
            peer.connect(path)
        except OSError:
            return False
        peer.sendall((json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8"))
    return True


def native_frame(message: dict, msg_id: str, name: str) -> dict:
    from src.core.crosstalk.delivery.dispatcher import envelope

    body = f'<cross-session-message from="unknown" from-name="{name}" from-mode="bypass">\n{envelope(message)}\n</cross-session-message>'
    return {"msgV": 1, "msg_id": msg_id, "type": "user", "priority": "next",
            "message": {"role": "user", "content": body}}


async def _receipt_seen(info: Any, message: dict, msg_id: str, conversation: str) -> bool:
    presence = await asyncio.to_thread(conversation_presence, conversation, working_dir=info.session.working_dir)
    return bool(presence.path and await asyncio.to_thread(_receipt, Path(presence.path), msg_id, message,
                                                           conversation))


async def _frame_lost(info: Any, conversation: str) -> bool:
    if not info.tmux_session:
        return False
    registry = await asyncio.to_thread(
        registry_for_session, tmux_name=info.tmux_session,
        session_started_epoch=info.session.tmux_created_epoch, claude_session_uuid=conversation)
    if registry.verdict in (REG_ABSENT, REG_STALE):
        return True
    return registry.known and bool(registry.session_uuid) and registry.session_uuid != conversation


async def settle_after_wake(info: Any, message: dict) -> str | tuple[str, str]:
    receipt = str(message.get("reason") or "").split(":", 2)
    if (len(receipt) == 3 and re.fullmatch(r"[0-9a-f]{32}", receipt[1])
            and re.fullmatch(r"[0-9a-fA-F-]{36}", receipt[2])
            and await _receipt_seen(info, message, receipt[1], receipt[2])):
        return "delivered"
    return "failed", "receiver is a different pane instance"


async def deliver(app: Any, info: Any, message: dict) -> str | tuple[str, str] | None:
    if app is not None:
        info = await app.state.session_manager.get_session_info(session_id=info.session.id)
        if (info is None or info.session.id != message['receiver_id']
                or info.session.tmux_created_epoch != message['receiver_epoch']):
            return "failed", "receiver instance changed before native delivery"
    target_conversation = conversation_id(info, message)
    pending = str(message.get("reason") or "")
    if pending.startswith("native_receipt_pending:"):
        receipt = pending.split(":", 2)
        msg_id = receipt[1]
        if not re.fullmatch(r"[0-9a-f]{32}", msg_id):
            return "failed", "invalid native receipt id"
        receipt_conversation = receipt[2] if len(receipt) == 3 else target_conversation
        if not receipt_conversation:
            return "held", pending
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', receipt_conversation):
            return "failed", "invalid native receipt conversation"
        if await _receipt_seen(info, message, msg_id, receipt_conversation):
            return "delivered"
        if await _frame_lost(info, receipt_conversation):
            logger.warning("crosstalk_claude_frame_lost", receiver_id=info.session.id, message_id=message["id"])
            return "failed", "native_frame_lost: the receiver's conversation no longer holds the queued message"
        return "held", pending
    if target_conversation is None:
        return None
    if _CLOSE in message["text"]:
        return None
    name = str(message.get("sender_name") or "carnivore")
    if not _NAME.fullmatch(name):
        return None
    registry = await asyncio.to_thread(
        registry_for_session, tmux_name=info.tmux_session,
        session_started_epoch=info.session.tmux_created_epoch,
        claude_session_uuid=target_conversation,
    )
    if not registry.known or not registry.pid or not registry.session_uuid or not registry.version or registry.version < (2, 1, 224):
        return None
    try:
        record = await asyncio.to_thread(read_pid_record, registry.pid)
        table = await asyncio.to_thread(read_process_table)
    except (MeasureError, OSError):
        return None
    proc = table.rows.get(registry.pid)
    if not record or not proc or not same_process_start(proc.lstart, str(record.get("procStart") or "")):
        return None
    if record.get("peerProtocol") != 1 or record.get("sessionId") != registry.session_uuid:
        return None
    path = record.get("messagingSocketPath")
    if not isinstance(path, str) or not path.startswith("/tmp/cc-socks/") or not path.endswith(".sock"):
        return None
    presence = await asyncio.to_thread(conversation_presence, registry.session_uuid, working_dir=info.session.working_dir)
    if presence.path is None:
        return None
    if app is not None:
        fresh = await app.state.session_manager.get_session_info(session_id=info.session.id)
        if fresh is None or fresh.session.tmux_created_epoch != message["receiver_epoch"]:
            return "failed", "receiver instance changed before native delivery"
        if fresh.activity_status == "question" or fresh.startup_gate != "ready":
            return "held", "receiver has an open dialog or startup gate"
        if conversation_id(fresh, message) != target_conversation:
            return "held", "receiver conversation changed before native delivery"
    msg_id = uuid.uuid4().hex
    from src.core.crosstalk import store

    if not await asyncio.to_thread(store.mark_native_pending, message["id"], msg_id,
                                   conversation_id=target_conversation):
        return "failed", "native message no longer claimed"
    frame = native_frame(message, msg_id, name)
    try:
        connected = await asyncio.to_thread(_post, path, frame)
    except OSError as exc:
        logger.warning("crosstalk_claude_socket_failed", receiver_id=info.session.id, error_type=type(exc).__name__)
        return "failed", "native_delivery_uncertain"
    if not connected:
        return None
    for _ in range(180):
        if await asyncio.to_thread(_receipt, Path(presence.path), msg_id, message, target_conversation):
            return "delivered"
        await asyncio.sleep(0.25)
    logger.warning("crosstalk_claude_receipt_missing", receiver_id=info.session.id, message_id=message["id"])
    return "held", "native_receipt_pending:" + msg_id + ":" + target_conversation


from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import structlog
import websockets

from src.core.crosstalk.delivery.identity import conversation_id

logger = structlog.get_logger(__name__)
_THREAD_ID = re.compile(r"^[0-9a-fA-F-]{36}$")


def _open_dialog(status: dict) -> bool:
    return bool({'waitingOnApproval', 'waitingOnUserInput'} & set(status.get('activeFlags') or ()))


def socket_path(session_id: str) -> Path:
    if not session_id or len(session_id) > 256:
        raise ValueError("invalid session id for Codex socket")
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
    return Path("/tmp") / f"carnivore-codex-{os.getuid()}" / f"{digest}.sock"


class RpcError(RuntimeError):
    pass


async def _request(ws: Any, method: str, params: dict, number: int) -> dict:
    await ws.send(json.dumps({"jsonrpc": "2.0", "id": number, "method": method, "params": params}))
    while True:
        row = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
        if row.get("id") != number:
            continue
        if "error" in row:
            raise RpcError(str(row["error"].get("message", "app-server error")))
        result = row.get("result")
        if not isinstance(result, dict):
            raise RpcError("app-server response has no result object")
        return result


async def deliver(app: Any, info: Any, message: dict) -> str | tuple[str, str] | None:
    session_id = str(info.session.id)
    if app is not None:
        info = await app.state.session_manager.get_session_info(session_id=session_id)
        if (info is None or info.session.id != message['receiver_id']
                or info.session.tmux_created_epoch != message['receiver_epoch']):
            return "failed", "receiver instance changed before native delivery"
    thread_id = str(conversation_id(info, message) or "")
    if not _THREAD_ID.fullmatch(thread_id):
        return None
    path = socket_path(session_id)
    try:
        directory = path.parent.stat()
    except OSError:
        return None
    if directory.st_uid != os.getuid() or directory.st_mode & 0o077 or not path.exists():
        return None
    from src.core.crosstalk.delivery.dispatcher import envelope

    payload = {"threadId": thread_id, "input": [{"type": "text", "text": envelope(message)}]}
    accepted = False
    submitted = False
    try:
        async with websockets.unix_connect(str(path), open_timeout=3) as ws:
            await _request(ws, "initialize", {"clientInfo": {"name": "carnivore-crosstalk", "version": "1.0.0"},
                                              "capabilities": {}}, 1)
            await ws.send(json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}))
            loaded = await _request(ws, "thread/loaded/list", {}, 2)
            if thread_id not in loaded.get("data", []):
                return None
            details = await _request(ws, "thread/read", {"threadId": thread_id, "includeTurns": False}, 3)
            thread = details.get("thread") or {}
            if thread.get("id") != thread_id:
                return None
            if _open_dialog(thread.get("status") or {}):
                return "held", "receiver has an open dialog or startup gate"
            active = None
            if (thread.get("status") or {}).get("type") == "active":
                with_turns = await _request(ws, "thread/read", {"threadId": thread_id, "includeTurns": True}, 4)
                turns = (with_turns.get("thread") or {}).get("turns") or []
                active = turns[-1] if turns and turns[-1].get("status") == "inProgress" else None
                if active is None:
                    return None
            if app is not None:
                fresh = await app.state.session_manager.get_session_info(session_id=session_id)
                if fresh is None or fresh.session.tmux_created_epoch != message["receiver_epoch"]:
                    return "failed", "receiver instance changed before native delivery"
                if fresh.activity_status == "question" or fresh.startup_gate != "ready":
                    return "held", "receiver has an open dialog or startup gate"
                if conversation_id(fresh, message) != thread_id:
                    return "held", "receiver conversation changed before native delivery"
            if active:
                payload["expectedTurnId"] = active["id"]
                submitted = True
                await _request(ws, "turn/steer", payload, 5)
            else:
                submitted = True
                await _request(ws, "turn/start", payload, 5)
            accepted = True
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException, RpcError, ValueError, KeyError) as exc:
        logger.warning("crosstalk_codex_rpc_failed", receiver_id=session_id, error_type=type(exc).__name__)
        return "failed" if submitted else None
    return "delivered" if accepted else "failed"

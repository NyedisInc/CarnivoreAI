
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Optional

import structlog

from src.core.mcp import channel as channel_events
from src.core.mcp import aliases, federated, instructions, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp_health.first_hand import LINKS

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07")

MAX_BODY_BYTES = 256 * 1024
MAX_BATCH = 20
MAX_READ_BYTES = max([MAX_BODY_BYTES, *tools.LARGE_BODY_TOOLS.values()])

logger = structlog.get_logger()

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
SESSION_EXPIRED = -32001
SESSION_ID_HEADER = "Mcp-Session-Id"
FINGERPRINT_CHARS = 16

def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _result(msg_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


class BatchView:

    def __init__(self, manager: Any, app: Any = None, force_peers: bool = False) -> None:
        self._manager = manager
        self._force_peers = force_peers
        self.app = app
        self.gate_waited = False
        self._infos: Optional[list] = None
        self._peer_infos: Optional[list] = None

    def fresh(self) -> "BatchView":
        return BatchView(self._manager, self.app, force_peers=True)

    async def list_session_infos(self) -> list:
        if self._infos is None:
            if self.app is not None:
                from src.api.session_crud_routes import build_owner_listing

                self._infos = await build_owner_listing(self.app.state)
            else:
                self._infos = await self._manager.list_session_infos()
        return self._infos

    async def list_peer_infos(self) -> list:
        if self._peer_infos is None:
            self._peer_infos = await federated.peer_infos(force=self._force_peers)
        return self._peer_infos

    async def live_ids_now(self) -> set:
        local = await self._manager.list_session_infos()
        peers = await federated.peer_infos(force=True)
        return {i.session.id for i in local} | {i.session.id for i in peers}

    async def companion_info(self, target: str) -> Any:
        sid = self._manager._registry.find_hidden_id(target)
        return None if sid is None else await self._manager.get_session_info(sid)

    def capture_scrollback(self, lines: int, session_id: str) -> bytes:
        return self._manager.capture_scrollback(lines=lines, session_id=session_id)


def tool_fingerprint(caller: AgentCaller, channel: bool = False) -> str:
    blob = json.dumps([tools.tool_definitions(caller), instructions.guide(caller, channel=channel)],
                      sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:FINGERPRINT_CHARS]


def session_is_current(session_id: Optional[str], caller: AgentCaller, channel: bool = False) -> bool:
    if not session_id:
        return True
    head, dot, _ = session_id.partition(".")
    return bool(dot) and secrets.compare_digest(head.encode(), tool_fingerprint(caller, channel).encode())


def server_capabilities(channel: bool) -> dict:
    caps: dict = {"tools": {"listChanged": True}}
    if channel:
        caps["experimental"] = {channel_events.CAPABILITY: {}}
    return caps


async def handle_message(msg: Any, manager: Any, caller: AgentCaller, *, channel: bool = False) -> Optional[dict]:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(None, INVALID_REQUEST, "invalid request")
    method = msg.get("method")
    if not isinstance(method, str):
        return None
    if "id" not in msg:
        return None
    msg_id = msg["id"]
    params = msg.get("params")
    params = params if isinstance(params, dict) else {}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(msg_id, {
            "protocolVersion": asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
            "capabilities": server_capabilities(channel),
            "serverInfo": {"name": "carnivore", "version": "1"},
            "instructions": instructions.guide(caller, channel=channel),
        })
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": tools.tool_definitions(caller)})
    if method == "tools/call":
        name = params.get("name")
        if not tools.has_tool(name):
            return _error(msg_id, INVALID_PARAMS, f"unknown tool: {name!r}")
        if caller.external:
            logger.info("mcp_external_call", client=caller.token_name, scope=caller.scope, tool=name)
        return _result(msg_id, await tools.call_tool(manager, caller, name, params.get("arguments")))
    return _error(msg_id, METHOD_NOT_FOUND, f"method not found: {method[:80]}")


async def handle_body(
    raw: bytes, manager: Any, caller: AgentCaller, app: Any = None, *, channel: bool = False,
    session_id: Optional[str] = None,
) -> tuple[int, Optional[Any], dict[str, str]]:
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return 400, _error(None, PARSE_ERROR, "parse error"), {}
    batch = body if isinstance(body, list) else [body]
    if not batch or len(batch) > MAX_BATCH:
        return 400, _error(None, INVALID_REQUEST, "batch must hold 1 to 20 messages"), {}
    starts = any(isinstance(m, dict) and m.get("method") == "initialize" for m in batch)
    if not starts and not session_is_current(session_id, caller, channel):
        logger.info("mcp_session_stale", client=caller.token_name or caller.tmux_name)
        return 404, _error(None, SESSION_EXPIRED, "session expired: the tool list changed; initialize again"), {}
    if not caller.external:
        for message in batch:
            if isinstance(message, dict) and isinstance(message.get("method"), str):
                LINKS.record(caller.tmux_name, message["method"])
    view = BatchView(manager, app)
    replies = [r for r in [await handle_message(m, view, caller, channel=channel) for m in batch] if r is not None]
    headers: dict[str, str] = {}
    if starts:
        headers[SESSION_ID_HEADER] = f"{tool_fingerprint(caller, channel)}.{secrets.token_urlsafe(16)}"
    if not replies:
        return 202, None, headers
    return 200, (replies if isinstance(body, list) else replies[0]), headers


def rpc_methods(raw: bytes) -> str:
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return ""
    batch = body if isinstance(body, list) else [body]
    names = [m["method"][:40] for m in batch[:MAX_BATCH] if isinstance(m, dict) and isinstance(m.get("method"), str)]
    return ",".join(names)[:120]


def body_allowed(raw: bytes, caller: AgentCaller) -> bool:
    if len(raw) <= MAX_BODY_BYTES:
        return True
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return False
    params = body.get("params") if isinstance(body, dict) and body.get("method") == "tools/call" else None
    name = params.get("name") if isinstance(params, dict) else None
    return isinstance(name, str) and len(raw) <= tools.LARGE_BODY_TOOLS.get(aliases.canonical(name), 0) and tools.allowed(caller, name)

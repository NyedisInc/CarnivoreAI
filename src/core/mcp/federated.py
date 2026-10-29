
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from types import SimpleNamespace
from typing import Any, Optional
from urllib.parse import urlencode

import structlog
from fastapi import HTTPException

from src.core.federation import peer_forward, peer_hosts, peer_links, peer_listing
from src.core.federation.peer_forward import SID, UUID
from src.core.hosts.ddl import LOCAL_HOST_KEY
from src.core.mcp.common import ToolError

logger = structlog.get_logger()

FIRST_FRAME_SECONDS = 3.0
PAINT_WINDOW_SECONDS = 1.0
CLOSE_SECONDS = 1.0
SOCKET_SECONDS = 6.0
MAX_SCREEN_BYTES = 256 * 1024


def is_remote(info: Any) -> bool:
    return info.host_key != LOCAL_HOST_KEY


async def peer_infos(*, force: bool = False) -> list:
    from src.api import peer_auth

    return await peer_listing.peer_rows(peer_auth.open_db, force=force)


def _target(wire_id: str) -> Optional[peer_forward.Target]:
    from src.api import peer_auth

    with closing(peer_auth.open_db()) as conn:
        return peer_forward.resolve(conn, wire_id)


def _client(target: peer_forward.Target) -> Any:
    links = peer_links.LINKS
    client = links.client(target.peer.peer_install_id) if links is not None else None
    if client is None:
        raise ToolError(f"{target.peer.label} is not connected right now")
    return client


def _message(data: Any, status: int) -> str:
    detail = data.get("detail") if isinstance(data, dict) else data
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("detail") or detail.get("reason") or detail.get("code") or detail
    return f"refused ({status}): {str(detail)[:300]}"


async def _send(peer: Any, rule: peer_forward.Rule, path: str, body: Any) -> dict:
    from src.api import peer_route_guard

    try:
        response = await peer_route_guard.forward_reply(rule, peer, path, body)
    except HTTPException as exc:
        raise ToolError(_message(exc.detail, exc.status_code)) from exc
    try:
        data = json.loads(response.body)
    except ValueError:
        data = None
    if 200 <= response.status_code < 300:
        return data if isinstance(data, dict) else {}
    if response.status_code in (404, 405) and isinstance(data, dict) and data.get("detail") in ("Not Found", "Method Not Allowed"):
        raise ToolError(f"{peer.label} runs an older Carnivore without this action")
    raise ToolError(_message(data, response.status_code))


async def forward(info: Any, method: str, template: str, body: Any = None) -> dict:
    rule = peer_forward.RULES[(method, template)]
    target = await asyncio.to_thread(_target, info.session.id)
    if target is None:
        raise ToolError("that paired computer is no longer linked")
    form = rule.ref[2]  # type: ignore[index]
    value = target.uuid if form == UUID else (
        peer_listing.owner_session_id(target.peer.key, target.name) or target.name) if form == SID else target.name
    if value is None:
        raise ToolError(f"{target.peer.label} has not listed this session yet")
    where, name, _ = rule.ref  # type: ignore[misc]
    path, sent = peer_forward.build_request(rule, value, {name: info.session.id} if where == "path" else {}, [], body)
    return await _send(target.peer, rule, path, sent)


async def find_peer(name: str) -> Any:
    from src.api import peer_auth

    def read() -> list:
        with closing(peer_auth.open_db()) as conn:
            return peer_hosts.list_peers(conn)

    for peer in await asyncio.to_thread(read):
        if name.lower() in (peer.key.lower(), str(peer.label).lower()):
            return peer
    raise ToolError(f"no paired computer named {name!r}; the host column of sessions_list names them")


def standin(peer: Any) -> Any:
    """A row-shaped stand-in for a session that does not exist yet (a create's gate target). Output: SimpleNamespace."""
    return SimpleNamespace(session=SimpleNamespace(id=f"remote:{peer.key}:new"), tmux_session="",
                           host_key=peer.key, host_label=peer.label)


async def create(peer: Any, body: dict) -> dict:
    rule = peer_forward.RULES[("POST", "/sessions")]
    path, sent = peer_forward.build_request(rule, "local", {}, [], body)
    created = await _send(peer, rule, path, sent)
    if not isinstance(created.get("id"), str):
        raise ToolError(f"{peer.label} answered without a session id")
    return created


async def resolved_again(wire_id: str, epoch: Optional[int]) -> Any:
    for info in await peer_infos(force=True):
        if info.session.id == wire_id:
            if info.session.tmux_created_epoch != epoch:
                raise ToolError("the target is now a different pane than the one you asked about; nothing was done")
            return info
    raise ToolError("the target session is no longer listed on that computer; nothing was done")


def pane_live(info: Any) -> bool:
    return info.activity_status != "dead"


async def _screen_socket(info: Any, query: dict, action: Any) -> Any:
    from src.core.federation import peer_terminal_proxy as proxy

    target = await asyncio.to_thread(_target, info.session.id)
    if target is None:
        raise ToolError("that paired computer is no longer linked")
    client = _client(target)

    async def run() -> Any:
        upstream = await proxy.connect_upstream(client, "/ws/terminal?" + urlencode({"session_id": target.name, **query}))
        try:
            return await action(upstream)
        finally:
            try:
                await asyncio.wait_for(upstream.close(), CLOSE_SECONDS)
            except (asyncio.TimeoutError, OSError):
                logger.info("mcp_peer_socket_close_slow", peer=target.peer.key)

    try:
        return await asyncio.wait_for(run(), SOCKET_SECONDS)
    except proxy.PeerUnavailable:
        raise ToolError(f"{target.peer.label} did not accept a terminal connection") from None
    except (asyncio.TimeoutError, OSError) as exc:
        raise ToolError(f"{target.peer.label} did not answer in time ({type(exc).__name__})") from None
    except Exception as exc:  # noqa: BLE001
        logger.info("mcp_peer_socket_failed", peer=target.peer.key, error_type=type(exc).__name__)
        raise ToolError(f"{target.peer.label} closed the terminal connection ({type(exc).__name__})") from None


async def read_screen(info: Any) -> bytes:
    async def action(upstream: Any) -> bytes:
        loop = asyncio.get_running_loop()
        chunks: list[bytes] = []
        size, deadline = 0, None
        while size < MAX_SCREEN_BYTES:
            wait = FIRST_FRAME_SECONDS if deadline is None else deadline - loop.time()
            if wait <= 0:
                break
            try:
                frame = await asyncio.wait_for(upstream.recv(), wait)
            except asyncio.TimeoutError:
                break
            if isinstance(frame, bytes):
                chunks.append(frame)
                size += len(frame)
                if deadline is None:
                    deadline = loop.time() + PAINT_WINDOW_SECONDS
            elif '"terminal.ready"' in frame:
                break
        return b"".join(chunks)[:MAX_SCREEN_BYTES]

    return await _screen_socket(info, {"observer": "1"}, action)


async def send_input(info: Any, data: bytes) -> None:
    async def action(upstream: Any) -> None:
        while True:
            frame = await upstream.recv()
            if isinstance(frame, str) and '"terminal.ready"' in frame:
                break
        await upstream.send(data)

    await _screen_socket(info, {"observer": "1", "interactive": "1"}, action)

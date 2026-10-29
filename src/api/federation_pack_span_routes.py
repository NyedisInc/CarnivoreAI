
from __future__ import annotations

import asyncio
from contextlib import closing
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api import peer_auth
from src.api.peer_auth import Principal, require_peer
from src.api.swarm_switch_routes import require_swarm_on
from src.core import db
from src.core.federation import peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.mcp import tool_families
from src.core.mcp.caller import AgentCaller
from src.core.pack.machines import capabilities as pack_capabilities
from src.core.pack.machines import restrictions
from src.core.pack.span import body_host, proxy_client, proxy_server, refresh_fanout, remote_body

logger = structlog.get_logger()
router = APIRouter(prefix="/federation", tags=["federation"])

_require_replica, _require_proxy, _require_refresh = require_peer("replica"), require_peer("swarm-proxy"), require_peer("refresh")
pack_capabilities.register("swarm.remote_body", "swarm.proxy", "pack.refresh", pack_capabilities.CAP_TASK_MANAGER_NAMES)
restrictions.set_agent_counter(body_host.hosted_count)


def _peer(principal: Principal) -> str:
    if not principal.is_peer or principal.grant is None:
        raise HTTPException(403, {"code": "peer_token_required"})
    return principal.grant.peer_install_id


@router.post("/swarm/body")
async def host_body(packet: body_host.BodyPacket, request: Request, principal: Principal = Depends(_require_replica)) -> Dict[str, Any]:
    """Run a pane for the caller's agent here. Output: ``{id, tmux_name, working_dir, epoch, session_uuid}``. Raises: 403 ``pack_restricted``, 409, 422, 503."""
    home = _peer(principal)
    require_swarm_on()
    try:
        return await body_host.host(request, home, packet)
    except body_host.BodyRefused as exc:
        raise HTTPException(exc.status, {"code": exc.code, "detail": exc.detail}) from exc


class SleepBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    teardown: bool = False


@router.post("/swarm/body/{home_agent_id}/sleep")
async def sleep_body(home_agent_id: int, body: SleepBody, principal: Principal = Depends(_require_replica)) -> Dict[str, Any]:
    """Send the body's changed memory files to the home, then (teardown) mark the body gone. Output: ``{written_back, kept_both}``."""
    from src.config import settings as app_settings

    home = _peer(principal)
    state_dir = app_settings.get_state_dir()
    mirror = body_host.mirror_dir(state_dir, home, home_agent_id)

    def read() -> Optional[List[Dict[str, Any]]]:
        with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn:
            if conn.execute("SELECT 1 FROM swarm_remote_bodies WHERE home_install_id = ? AND home_agent_id = ?", (home, home_agent_id)).fetchone() is None:
                return None
        from src.core.pack.span import memory_mirror

        return memory_mirror.changes(mirror)

    changed = await asyncio.to_thread(read)
    if changed is None:
        raise HTTPException(404, {"code": "unknown_body"})
    answer: Dict[str, Any] = {"applied": [], "kept_both": []}
    if changed:
        links = peer_links.LINKS
        client = links.client(home) if links is not None else None
        if client is None:
            raise HTTPException(503, {"code": "home_not_connected"})
        try:
            reply = await client.request("POST", "/api/v1/federation/swarm/memory/writeback",
                                         json={"home_agent_id": home_agent_id, "files": changed}, timeout=30)
        except (PeerUnreachable, PeerRefused) as exc:
            raise HTTPException(503, {"code": "writeback_unreachable", "detail": type(exc).__name__}) from exc
        if reply.status_code != 200:
            raise HTTPException(502, {"code": "writeback_refused", "detail": reply.status_code})
        answer = reply.json()
    if body.teardown:
        def tear() -> None:
            with closing(db.connect(db.db_path_for(state_dir), create=False)) as conn, conn:
                conn.execute("UPDATE swarm_remote_bodies SET torn_down_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                             "WHERE home_install_id = ? AND home_agent_id = ?", (home, home_agent_id))

        await asyncio.to_thread(tear)
    return {"written_back": len(changed), "kept_both": answer.get("kept_both", [])}


@router.post("/swarm/proxy")
async def swarm_proxy(call: proxy_server.ProxyCall, request: Request, principal: Principal = Depends(_require_proxy)) -> Dict[str, Any]:
    """Run a remote body's Swarm or Task Manager tool call as the home's own action (F20). Output: ``{result}``. Raises: 403 ``proxy_binding_refused``, 409.
    """
    peer = _peer(principal)
    family = tool_families.family_of(call.tool)
    if family is not None and family.key == "swarm":
        require_swarm_on()
    return await proxy_server.run(request.app, peer, call)


class WritebackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_agent_id: int = Field(ge=1)
    files: List[Dict[str, Any]] = Field(max_length=400)


@router.post("/swarm/memory/writeback")
async def memory_writeback(body: WritebackBody, principal: Principal = Depends(_require_proxy)) -> Dict[str, Any]:
    """Apply a host's memory changes for a feature agent (a file whose home copy moved is kept beside it). Output: ``{applied, kept_both}``."""
    install = _peer(principal)

    def label() -> str:
        with closing(peer_auth.open_db()) as conn:
            peer = peer_hosts.get(conn, install)
        return str(peer.label) if peer else "a host"

    return await proxy_server.apply_writeback(install, body.home_agent_id, body.files, await asyncio.to_thread(label))


class BoardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_uid: str = Field(min_length=8, max_length=64)
    args: Dict[str, Any] = Field(default_factory=dict)


@router.post("/pack/board/{verb}")
async def board_verb(verb: str, body: BoardBody, request: Request, principal: Principal = Depends(_require_proxy)) -> Dict[str, Any]:
    """
    Raises: 403 ``proxy_binding_refused`` (the caller does not replicate that project), 409 ``tool_not_proxied`` or ``not_local``.
    """
    from src.config import settings as app_settings
    from src.core.mcp import aliases, tools
    from src.core.mcp.protocol import BatchView

    install = _peer(principal)
    if not (verb.startswith("huddle_") or aliases.was_renamed(verb)) or verb not in tools._TOOLS:
        raise proxy_server.refused("tool_not_proxied", 409)
    if proxy_server._names_remote(body.args):
        raise proxy_server.refused("not_local", 409)

    def replicates() -> bool:
        with closing(db.connect(db.db_path_for(app_settings.get_state_dir()), create=False)) as conn:
            return conn.execute("SELECT 1 FROM project_replicas WHERE project_uid = ? AND install_id = ?", (body.project_uid, install)).fetchone() is not None

    if not await asyncio.to_thread(replicates):
        raise proxy_server.refused()
    caller = AgentCaller(session_id=f"mcp-token:peer-{install[:8]}", tmux_name=f"mcp-token:peer-{install[:8]}",
                         current_session_id=f"mcp-token:peer-{install[:8]}", token_name=f"peer-{install[:8]}")
    return {"result": await tools.call_tool(BatchView(request.app.state.session_manager, request.app), caller, verb, body.args)}


@router.post("/pack/refresh", status_code=202)
async def refresh_install(principal: Principal = Depends(_require_refresh)) -> Any:
    _peer(principal)
    try:
        return await refresh_fanout.run_install_refresh()
    except LookupError as exc:
        raise HTTPException(501, {"code": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(409, {"code": str(exc)}) from exc

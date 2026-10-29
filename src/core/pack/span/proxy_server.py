
from __future__ import annotations

from pathlib import Path
import asyncio
import json
import sqlite3
from contextlib import closing
from typing import Any, Dict, Optional

import structlog
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.core import db
from src.core.hosts.identity import remote_session_id
from src.core.mcp.caller import AgentCaller
from src.core.pack.span import memory_mirror, proxy_client
from src.core.swarm import memory, store

logger = structlog.get_logger()

MAX_RESULT_CHARS = 48 * 1024


class ProxyCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1, max_length=96)
    args: Dict[str, Any] = Field(default_factory=dict)
    body_session_uuid: str = Field(min_length=8, max_length=128)
    body_epoch: Optional[int] = None
    project_uid: str = Field(min_length=8, max_length=64)
    home_agent_id: int = Field(ge=1)


def refused(code: str = "proxy_binding_refused", status: int = 403) -> HTTPException:
    return HTTPException(status, {"code": code})


def _names_remote(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("remote:")
    if isinstance(value, dict):
        return any(_names_remote(v) for v in value.values())
    if isinstance(value, list):
        return any(_names_remote(v) for v in value)
    return False


def bind(conn: sqlite3.Connection, peer_install_id: str, body_session_uuid: str, home_agent_id: int) -> Dict[str, Any]:
    from src.core.federation import peer_hosts, shadow_rows

    host = peer_hosts.get(conn, peer_install_id)
    if host is None:
        raise refused("peer_unpaired", 401)
    shadow = conn.execute("SELECT id, tmux_name FROM sessions WHERE session_uuid = ? AND origin = ? AND host_key = ?",
                          (shadow_rows.shadow_uuid(peer_install_id, body_session_uuid), shadow_rows.PEER_ORIGIN, host.key)).fetchone()
    if shadow is None:
        raise refused()
    agent = store.get_agent_by_session_row(conn, int(shadow[0]))
    if agent is None or agent["torn_down_at"] is not None or agent.get("host_key") != host.key or agent["id"] != home_agent_id:
        raise refused()
    return {"agent": agent, "row_id": int(shadow[0]), "tmux_name": str(shadow[1]), "host_key": host.key}


async def _epoch_ok(row_id: int, epoch: Optional[int]) -> bool:
    from src.core.mcp import federated

    info = next((i for i in await federated.peer_infos() if getattr(i, "session_row_id", None) == row_id), None)
    return info is not None and epoch is not None and info.session.tmux_created_epoch == epoch


async def run(app: Any, peer_install_id: str, call: ProxyCall) -> Dict[str, Any]:
    from src.config import settings as app_settings
    from src.core.mcp import tools
    from src.core.mcp.protocol import BatchView

    if not proxy_client.is_proxied(call.tool) or call.tool not in tools._TOOLS:
        raise refused("tool_not_proxied", 409)
    if _names_remote(call.args):
        raise refused("not_local", 409)

    def read() -> Dict[str, Any]:
        with closing(db.connect(db.db_path_for(app_settings.get_state_dir()), create=False)) as conn:
            bound = bind(conn, peer_install_id, call.body_session_uuid, call.home_agent_id)
            project = conn.execute("SELECT 1 FROM projects WHERE uid = ? AND pack_state != 'replica'", (call.project_uid,)).fetchone()
            if project is None:
                raise refused("project_not_home", 409)
            return bound

    bound = await asyncio.to_thread(read)
    if not await _epoch_ok(bound["row_id"], call.body_epoch):
        raise refused()
    wire = remote_session_id(bound["host_key"], bound["tmux_name"])
    caller = AgentCaller(session_id=wire, tmux_name=bound["tmux_name"], current_session_id=wire, proxied_agent_id=bound["agent"]["id"])
    result = await tools.call_tool(BatchView(app.state.session_manager, app), caller, call.tool, call.args)
    if len(json.dumps(result, default=str)) > MAX_RESULT_CHARS:
        result = {"content": [{"type": "text", "text": "[the result was cut: it is over 48 KiB; ask for less]"}], "isError": True}
    return {"result": result}


async def apply_writeback(peer_install_id: str, home_agent_id: int, files: list, label: str) -> Dict[str, Any]:
    from datetime import datetime, timezone

    from src.config import settings as app_settings
    from src.core.swarm import body

    def read() -> Dict[str, Any]:
        with closing(db.connect(db.db_path_for(app_settings.get_state_dir()), create=False)) as conn:
            from src.core.federation import peer_hosts

            host = peer_hosts.get(conn, peer_install_id)
            agent = store.get_agent(conn, home_agent_id)
        if host is None or agent is None or agent["torn_down_at"] is not None or agent.get("host_key") != host.key:
            raise refused()
        return agent

    agent = await asyncio.to_thread(read)
    if agent["memory_scope"] != memory.SCOPE_PROJECT:
        return {"applied": [], "kept_both": []}
    mem = memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        done = await asyncio.to_thread(memory_mirror.apply_writeback, mem, files, label, stamp)
    except (ValueError, memory.SwarmFileError) as exc:
        raise HTTPException(422, {"code": "bad_writeback", "detail": str(exc)[:200]}) from exc
    if done["kept_both"]:
        await body._card(agent, "memory kept both", f"{agent['display_name']} changed {', '.join(done['kept_both'])} on {label} while it "
                         "changed at home; both copies are kept (the other has .from- in its name).", f"memory_kept_both:{agent['id']}")
    return done

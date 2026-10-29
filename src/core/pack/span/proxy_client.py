
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import Any, Dict, Optional

import structlog

from src.core import db
from src.core.federation import peer_hosts, peer_links
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import _fail
from src.core.mcp import aliases
from src.core.pack.machines import capabilities as caps_mod
from src.core.pack.migrate import task_manager_names
from src.cplugs.sdk.tool_families import TASK_MANAGER_PREFIX

logger = structlog.get_logger()

PROXY_PATH = "/federation/swarm/proxy"
PROXIED_PREFIXES = ("swarm_", "huddle_", TASK_MANAGER_PREFIX)
HUDDLE_PREFIX = "huddle_"


def is_proxied(name: str) -> bool:
    from src.core.mcp.tool_families import SWARM_SWITCH_TOOLS

    return name.startswith(PROXIED_PREFIXES) and name not in SWARM_SWITCH_TOOLS


def wire_tool_name(name: str, home_capabilities: Any) -> str:
    retired = aliases.retired_name(name)
    if retired is None or caps_mod.has(home_capabilities, caps_mod.CAP_TASK_MANAGER_NAMES):
        return name
    return retired


def _find(row_id: int) -> Optional[Dict[str, Any]]:
    from src.config import settings as app_settings

    try:
        with closing(db.connect(db.db_path_for(app_settings.get_state_dir()), create=False)) as conn:
            if not conn.execute("SELECT 1 FROM swarm_remote_bodies WHERE torn_down_at IS NULL LIMIT 1").fetchone():
                return None
            row = conn.execute(
                "SELECT b.home_install_id, b.home_agent_id, b.project_uid, s.session_uuid FROM swarm_remote_bodies b "
                "JOIN sessions s ON s.id = b.session_row_id WHERE b.session_row_id = ? AND b.torn_down_at IS NULL", (row_id,)).fetchone()
            return dict(row) if row else None
    except (sqlite3.Error, OSError, db.DatastoreUnreadableError):
        return None


async def maybe_forward(manager: Any, caller: AgentCaller, name: str, args: Any) -> Optional[dict]:
    if caller.external or caller.proxied_agent_id or not is_proxied(name):
        return None
    info = next((i for i in await manager.list_session_infos()
                 if i.session.id == caller.current_session_id and i.tmux_session == caller.tmux_name), None)
    row_id = getattr(info, "session_row_id", None)
    found = await asyncio.to_thread(_find, int(row_id)) if row_id is not None else None
    if found is None:
        return None
    from src.api import peer_auth

    def label() -> str:
        with closing(peer_auth.open_db()) as conn:
            peer = peer_hosts.get(conn, found["home_install_id"])
        return str(peer.label) if peer else "the home computer"

    links = peer_links.LINKS
    client = links.client(found["home_install_id"]) if links is not None else None
    if client is None:
        return _fail(f"home {await asyncio.to_thread(label)} is not connected; retry")
    sent = args if isinstance(args, dict) else {}
    if name.startswith(HUDDLE_PREFIX) or aliases.was_renamed(name):
        sent = task_manager_names.wire_state_args(sent)
    payload = {"tool": wire_tool_name(name, links.capabilities(found["home_install_id"])), "args": sent, "body_session_uuid": found["session_uuid"],
               "body_epoch": info.session.tmux_created_epoch, "project_uid": found["project_uid"], "home_agent_id": found["home_agent_id"]}
    try:
        answer = await client.request("POST", PROXY_PATH, json=payload, timeout=60)
    except (PeerUnreachable, PeerRefused) as exc:
        logger.info("swarm_proxy_unreachable", tool=name, error=type(exc).__name__)
        return _fail(f"home {await asyncio.to_thread(label)} did not answer; retry")
    if answer.status_code == 200:
        result = answer.json().get("result")
        return result if isinstance(result, dict) else _fail(f"{name} answered nothing")
    try:
        detail = answer.json().get("detail")
        code = detail.get("code") if isinstance(detail, dict) else str(detail)
    except ValueError:
        code = str(answer.status_code)
    return _fail(f"{name} was refused by the home computer ({code})")

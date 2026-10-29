
from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Dict, Optional

import structlog
from fastapi import HTTPException

from src.core import db
from src.core.swarm import body, project_agent, store
from src.core.swarm.names import shown_name

logger = structlog.get_logger()

LEADER_RANKS = ("alpha", "company", "project")


def confirm_matches(agent: Dict[str, Any], typed: Optional[str]) -> bool:
    return typed is not None and typed in (agent["display_name"], shown_name(agent))


def refusal(agent: Dict[str, Any], action: str) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "code": "leader_protected", "name": shown_name(agent), "rank": agent["rank"], "agent_id": agent["id"], "action": action,
        "message": f"{shown_name(agent)} is a {agent['rank']} leader; type its exact name to {action} it"})


def leader_row(conn: sqlite3.Connection, session_uuid: Optional[str], tmux_name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not session_uuid and not tmux_name:
        return None
    marks = ",".join("?" for _ in LEADER_RANKS)
    found = conn.execute(
        f"SELECT a.id FROM swarm_agents a JOIN sessions s ON s.id = a.session_row_id WHERE a.torn_down_at IS NULL AND a.rank IN ({marks}) "
        "AND (s.session_uuid = ? OR s.tmux_name = ?) LIMIT 1", (*LEADER_RANKS, session_uuid or "", tmux_name or "")).fetchone()
    return store.get_agent(conn, found[0]) if found else None


async def require_confirm(*, session_uuid: Optional[str] = None, tmux_name: Optional[str] = None, confirm_name: Optional[str], action: str = "close") -> None:
    try:
        agent = await body.run_db(lambda c: leader_row(c, session_uuid, tmux_name))
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        logger.warning("swarm_leader_guard_unreadable", error=str(exc)[:200])
        return
    if agent is not None and not confirm_matches(agent, confirm_name):
        raise refusal(agent, action)


async def follow_session_rename(tmux_name: Optional[str], new_label: str) -> None:
    if not tmux_name:
        return
    try:
        agent = await body.run_db(lambda c: leader_row(c, None, tmux_name))
        if agent is None or agent["display_name"] == new_label:
            return
        updated = await body.run_db(lambda c: store.update_agent(c, agent["id"], display_name=new_label))
        await asyncio.to_thread(project_agent.refresh_swarm_json, updated)
        logger.info("swarm_leader_followed_session_rename", agent_id=agent["id"], rank=agent["rank"])
    except (db.DatastoreUnreadableError, sqlite3.Error, store.AgentNotFound) as exc:
        logger.warning("swarm_leader_rename_follow_failed", error=str(exc)[:200])

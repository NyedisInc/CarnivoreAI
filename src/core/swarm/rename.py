
from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any, Dict, Optional, Tuple

import structlog

from src.core.swarm import body, naming_rules, project_agent, store, thread_port

logger = structlog.get_logger()

MAX_FORMER_NAMES = 10


class RenameRefused(ValueError):
    pass


def apply_name(conn: sqlite3.Connection, agent: Dict[str, Any], name: str, **fields: Any) -> Dict[str, Any]:
    former = naming_rules.former_names(agent)
    if agent["display_name"] != name and agent["display_name"] not in former:
        former.append(agent["display_name"])
    if agent["rank"] == "feature" and not agent.get("specialty") and "specialty" not in fields:
        fields["specialty"] = name
    updated = store.update_agent(conn, agent["id"], display_name=name,
                                 former_names=json.dumps(former[-MAX_FORMER_NAMES:]) if former else None, **fields)
    project_agent.relabel_session(conn, updated)
    return updated


def checked(conn: sqlite3.Connection, agent_id: int, raw_name: Any) -> Tuple[Dict[str, Any], str]:
    try:
        name = naming_rules.check_name(raw_name)
    except naming_rules.NameRefused as exc:
        raise RenameRefused(str(exc)) from None
    agent = store.get_agent(conn, agent_id)
    if agent is None or agent["torn_down_at"] is not None:
        raise store.AgentNotFound(agent_id)
    holder = naming_rules.name_holder(conn, agent, name)
    if holder is not None:
        raise RenameRefused(f"{holder['display_name']} (agent {holder['id']}) already holds the name {name!r} in this project")
    return agent, name


async def rename(agent_id: int, raw_name: Any) -> Dict[str, Any]:
    def work(conn: sqlite3.Connection) -> Dict[str, Any]:
        agent, name = checked(conn, agent_id, raw_name)
        return agent if agent["display_name"] == name else apply_name(conn, agent, name)

    updated = await body.run_db(work)
    await asyncio.to_thread(project_agent.refresh_swarm_json, updated)
    port = thread_port.get()
    if port is not None:
        await port.ensure_thread(updated["thread_key"], updated["display_name"])
    logger.info("swarm_agent_renamed", agent_id=agent_id, rank=updated["rank"])
    return updated


def is_own(caller: Optional[Dict[str, Any]], target: Dict[str, Any]) -> bool:
    return caller is not None and (target["id"] == caller["id"] or target.get("parent_id") == caller["id"])

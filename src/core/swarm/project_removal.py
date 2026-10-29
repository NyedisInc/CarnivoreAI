
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

import structlog

from src.core.swarm import routing, store, turn_off
from src.core.swarm.names import shown_name

logger = structlog.get_logger()


def agents_to_turn_off(conn: sqlite3.Connection, project_id: int) -> List[Dict[str, Any]]:
    root = store.get_project_agent(conn, project_id)
    if root is None:
        return []
    out: List[Dict[str, Any]] = []

    def walk(agent: Dict[str, Any]) -> None:
        for child in store.list_agents(conn, parent_id=agent["id"]):
            walk(child)
        out.append(agent)

    walk(root)
    return out


def company_agent_id(conn: sqlite3.Connection, project_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT a.id FROM projects p JOIN swarm_agents a ON a.rank = 'company' AND a.company_id = p.company_id "
        "AND a.torn_down_at IS NULL WHERE p.id = ?", (project_id,)).fetchone()
    return int(row[0]) if row else None


async def turn_off_agents(app_state: Any, project_id: int, agents: List[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for agent in agents:
        try:
            await turn_off.run(app_state, agent["id"])
        except store.AgentNotFound:
            continue
        names.append(shown_name(agent))
    if names:
        logger.info("project_agents_turned_off", project_id=project_id, count=len(names))
    return names


async def tell_company(app_state: Any, agent_id: int, project_name: str) -> bool:
    text = (f"The owner deleted the project {project_name}. It is gone for good, along with its project agent and the agents "
            "under it. Drop it from your plans and memory; do not try to reach it again.")
    return await routing.tell(app_state, agent_id, text, source="wake_prompt", authority="data",
                              ref=f"project_deleted:{project_name}", reason="crosstalk")

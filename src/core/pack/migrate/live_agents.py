
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.core.companion_shell.rows import exclude_clause
from src.core.pack.move import interrupt as interrupt_mod, turn

LIVE_AGENT_STATES = ("awake", "waking", "sleeping")


@dataclass(frozen=True)
class LiveAgent:

    session_uuid: str
    name: str
    agent_id: Optional[int] = None


def read(conn: sqlite3.Connection, project_id: int) -> Tuple[List[LiveAgent], List[str]]:
    sessions = conn.execute(f"SELECT id, session_uuid, COALESCE(title, session_uuid) FROM sessions WHERE project_id = ? AND lifecycle = 'running'{exclude_clause(conn)} ORDER BY id",
                            (project_id,)).fetchall()
    marks = ",".join("?" * len(LIVE_AGENT_STATES))
    swarm: Dict[Any, Any] = {}
    for r in conn.execute(f"SELECT id, display_name, state, session_row_id FROM swarm_agents WHERE project_id = ? AND torn_down_at IS NULL AND state IN ({marks}) ORDER BY id",
                          (project_id, *LIVE_AGENT_STATES)):
        swarm[r["session_row_id"] if r["session_row_id"] is not None else ("none", r["id"])] = r
    agents: List[LiveAgent] = []
    blockers: List[str] = []
    for row in sessions:
        body = swarm.pop(row[0], None)
        if body is not None and body["state"] != "awake":
            blockers.append(f"{body['display_name']} is {body['state']} right now; try again in a moment")
            continue
        agents.append(LiveAgent(str(row[1]), str(body["display_name"] if body is not None else row[2]), int(body["id"]) if body is not None else None))
    blockers += [f"{r['display_name']} is {r['state']} and is not running as a session here; put it to sleep first" for r in swarm.values()]
    return agents, blockers


async def classify(agents: List[LiveAgent], find: Any, stop_running: bool = False) -> Tuple[int, List[str]]:
    if find is None:
        return 0, []
    shells, blockers = 0, []
    for agent in agents:
        info = await find(agent.session_uuid)
        if info is None:
            continue
        if getattr(info, "startup_gate", "ready") != "ready":
            blockers.append(f"{agent.name} is waiting on a screen only you can answer; answer it, then plan again")
        elif interrupt_mod.is_running(info):
            if not stop_running:
                blockers.append(interrupt_mod.refusal_text([agent.name]))
        else:
            shells += turn.shells_only(info)
    return shells, blockers


def sentence(agents: int, shells: int, machine: str) -> str:
    line = f"{agents} {'agent' if agents == 1 else 'agents'} will stop here and continue on {machine}"
    return line + (f"; {shells} background {'shell' if shells == 1 else 'shells'} will be stopped" if shells else "")

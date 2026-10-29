
from __future__ import annotations

import sqlite3
from typing import Optional


def refusal(conn: sqlite3.Connection, project_id: int, name: str) -> Optional[str]:
    if conn.execute("SELECT 1 FROM companies WHERE hq_project_id = ?", (project_id,)).fetchone():
        return f"{name} is a company's own HQ folder, which its company agent already runs"
    home = conn.execute("SELECT display_name FROM swarm_agents WHERE project_id = ? AND rank IN ('alpha','company') "
                        "AND torn_down_at IS NULL", (project_id,)).fetchone()
    if home:
        return f"{name} is the home folder of {home[0]}, who already sits there"
    if conn.execute("SELECT 1 FROM swarm_agents WHERE project_id = ? AND rank = 'project' AND torn_down_at IS NULL", (project_id,)).fetchone():
        return f"{name} already has an agent"
    return None

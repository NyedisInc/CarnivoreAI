
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Tuple

from src.core.companies import accounts
from src.core.companies.store import CompanyNotFound
from src.core.swarm import learning, store


def lines(conn: sqlite3.Connection, agent: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    company_id = agent.get("company_id")
    if agent["rank"] != "company" or company_id is None:
        return [], []
    out = ["company projects (route the owner's orders to a project agent with crosstalk_send to agent:<id>):"]
    data: List[str] = []
    projects = conn.execute("SELECT id, display_name FROM projects WHERE company_id = ? AND archived_at IS NULL "
                            "ORDER BY display_name COLLATE NOCASE", (company_id,)).fetchall()
    hq = conn.execute("SELECT hq_project_id FROM companies WHERE id = ?", (company_id,)).fetchone()
    own = {agent.get("project_id"), hq[0] if hq else None}
    projects = [p for p in projects if p["id"] not in own]
    for project in projects:
        owner = store.get_project_agent(conn, project["id"])
        name = learning.one_line(project["display_name"])
        if owner:
            out.append(f"- {name}: agent {owner['id']}, {owner['state']} (its name is under 'from agents')")
            data += [f"project agent of {name}:", learning.QUOTE + learning.one_line(owner["display_name"])]
        else:
            out.append(f"- {name}: no agent yet; suggest turning one on with swarm_suggest (kind project, this name)")
    if not projects:
        out.append("- no projects yet")
    try:
        pointers = accounts.get_accounts(conn, company_id)
    except CompanyNotFound:
        pointers = {}
    out += ["", "account pointers: " + (", ".join(f"{learning.one_line(k)} {learning.one_line(v)}" for k, v in pointers.items()) or "none set")]
    waiting = conn.execute("SELECT kind, name FROM swarm_suggestions WHERE state = 'pending' AND company_id = ? ORDER BY id", (company_id,)).fetchall()
    if waiting:
        out += ["", "your suggestions waiting for the owner (their names are under 'from agents'):"]
        for n, sug in enumerate(waiting, 1):
            out.append(f"- {sug['kind']} suggestion {n}")
            data += [f"{sug['kind']} suggestion {n}:", learning.QUOTE + learning.one_line(sug["name"])[:200]]
    return out, data

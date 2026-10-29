
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from src.core.companies import store as companies
from src.core.swarm import body, company_agent, project_promote
from src.core.swarm.company_agent import CompanyMissing

COMPANY_PROMOTE_ORDERS = ("You were this company's HQ session and are now its Swarm company agent. This conversation continues unchanged; "
                          "from here on you run the company: read your desk, route the owner's orders to the project agents, and "
                          "suggest agents with swarm_suggest. Your standing rules are in your agent definition.")


def company_of_hq(conn: sqlite3.Connection, project_id: int) -> Optional[int]:
    row = conn.execute("SELECT id FROM companies WHERE hq_project_id = ?", (project_id,)).fetchone()
    return int(row[0]) if row else None


def _live_company_agent(conn: sqlite3.Connection, company_id: int) -> Optional[Dict[str, Any]]:
    return company_agent._company_state(conn, company_id)[1]


def _seat_refusal(conn: sqlite3.Connection, project: sqlite3.Row) -> Optional[str]:
    home = conn.execute("SELECT display_name FROM swarm_agents WHERE project_id = ? AND torn_down_at IS NULL "
                        "AND rank IN ('alpha', 'project', 'company')", (project["id"],)).fetchone()
    return f"{project['display_name']} is the home folder of {home[0]}, who already sits there" if home else None


def kind_for(company: Dict[str, Any]) -> project_promote.AgentKind:
    return project_promote.AgentKind(
        "company", COMPANY_PROMOTE_ORDERS, lambda conn, _project_id: _live_company_agent(conn, company["id"]),
        lambda conn, project, row_id: company_agent.insert_company_agent(conn, company, project["id"], project["root"], session_row_id=row_id),
        _seat_refusal)


async def promote_session(app_state: Any, session_uuid: str, company_id: int) -> Dict[str, Any]:
    def read(conn: sqlite3.Connection) -> Optional[tuple]:
        try:
            company = companies.get_company(conn, company_id)
        except companies.CompanyNotFound:
            return None
        return company, company["hq_project_id"]

    found = await body.run_db(read)
    if found is None:
        raise CompanyMissing("no such company")
    company, hq_project_id = found
    if hq_project_id is None:
        raise project_promote.PromoteRefused(f"{company['name']} has no HQ folder yet; turn its agent on first, or set its HQ project")
    return await project_promote.promote_session(app_state, session_uuid, hq_project_id, kind_for(company))


async def company_for_project(project_id: int) -> Optional[int]:
    return await body.run_db(lambda conn: company_of_hq(conn, project_id))


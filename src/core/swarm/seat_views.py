
from __future__ import annotations

import sqlite3
from typing import List, Optional

from src.core.swarm import alpha, project_removal
from src.core.swarm.names import shown_name
from src.cplugs.sdk.swarm import SeatRef


LEAD_RANKS = ("project", "company")


def agent_seats(conn: sqlite3.Connection) -> List[SeatRef]:
    rows = conn.execute(
        "SELECT a.id, a.rank, a.project_id, a.session_row_id, a.display_name, s.session_uuid, s.archived_at "
        "FROM swarm_agents a LEFT JOIN sessions s ON s.id = a.session_row_id WHERE a.torn_down_at IS NULL ORDER BY a.id").fetchall()
    out: List[SeatRef] = []
    for r in rows:
        has_body_row = r["session_row_id"] is not None
        gone = has_body_row and (r["session_uuid"] is None or r["archived_at"] is not None)
        out.append(SeatRef(agent_id=r["id"], rank=r["rank"],
                           project_key=str(r["project_id"]) if r["rank"] in LEAD_RANKS and r["project_id"] is not None else None,
                           session_uuid=r["session_uuid"], body_gone=bool(gone), display_name=shown_name(dict(r))))
    return out


def fallback_seat(conn: sqlite3.Connection, project_id: int) -> Optional[SeatRef]:
    wanted = project_removal.company_agent_id(conn, project_id)
    if wanted is None:
        top = alpha.live_alpha(conn)
        wanted = top["id"] if top else None
    return next((s for s in agent_seats(conn) if s.agent_id == wanted), None) if wanted is not None else None
